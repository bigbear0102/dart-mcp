#!/usr/bin/env python3
"""
DART MCP Server - 대한민국 전자공시시스템 (DART) OpenAPI MCP 서버

DS001: 공시정보 (Disclosure Information)
DS002: 정기보고서 주요정보 (Periodic Report Key Information)
DS003: 정기보고서 재무정보 (Periodic Report Financial Information)
DS004: 지분공시 종합정보 (Equity Disclosure Information)
DS005: 주요사항보고서 주요정보 (Major Issue Report Information)
DS006: 증권신고서 주요정보 (Securities Registration Statement Information)
"""

import io
import json
import os
import sys
import zipfile
from enum import Enum
from typing import Optional, List
from xml.etree import ElementTree as ET

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict, field_validator

# ─── Constants ────────────────────────────────────────────────────────────────

DART_BASE_URL = "https://opendart.fss.or.kr/api"
API_KEY = os.environ.get("DART_API_KEY", "")

# ─── Server Init ──────────────────────────────────────────────────────────────

mcp = FastMCP("dart_mcp")

# ─── Enums ────────────────────────────────────────────────────────────────────

class ReportCode(str, Enum):
    Q1     = "11013"  # 1분기보고서
    HALF   = "11012"  # 반기보고서
    Q3     = "11014"  # 3분기보고서
    ANNUAL = "11011"  # 사업보고서


class CorpClass(str, Enum):
    KOSPI  = "Y"  # 유가증권
    KOSDAQ = "K"  # 코스닥
    KONEX  = "N"  # 코넥스
    OTHER  = "E"  # 기타


class DisclosureType(str, Enum):
    REGULAR       = "A"  # 정기공시
    MAJOR_MATTER  = "B"  # 주요사항보고
    ISSUANCE      = "C"  # 발행공시
    LISTING       = "D"  # 지분공시
    CORP_GOVERN   = "E"  # 기업지배구조
    FUND          = "F"  # 펀드공시
    SECURITIES    = "G"  # 증권신고
    PROXY         = "H"  # 의결권대리행사권유
    ASSET_BACKED  = "I"  # 자산유동화
    DEBT_RECOVERY = "J"  # 거래소공시(자율)


class FinancialStatementDiv(str, Enum):
    INDIVIDUAL   = "OFS"  # 별도재무제표
    CONSOLIDATED = "CFS"  # 연결재무제표


class FinancialIndexCode(str, Enum):
    STABILITY    = "M210000"  # 안정성 지표
    PROFITABILITY = "M220000"  # 수익성 지표
    GROWTH       = "M230000"  # 성장성 지표
    ACTIVITY     = "M240000"  # 활동성 지표


class XbrlStatementDiv(str, Enum):
    BS1  = "BS1"   # 재무상태표(연결)
    BS2  = "BS2"   # 재무상태표(별도)
    IS1  = "IS1"   # 손익계산서(연결)
    IS2  = "IS2"   # 손익계산서(별도)
    CIS1 = "CIS1"  # 포괄손익계산서(연결)
    CIS2 = "CIS2"  # 포괄손익계산서(별도)
    CF1  = "CF1"   # 현금흐름표(연결)
    CF2  = "CF2"   # 현금흐름표(별도)
    SCE1 = "SCE1"  # 자본변동표(연결)
    SCE2 = "SCE2"  # 자본변동표(별도)

# ─── Shared Utilities ─────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = API_KEY or os.environ.get("DART_API_KEY", "")
    if not key:
        raise ValueError(
            "DART API 키가 설정되지 않았습니다. "
            "환경변수 DART_API_KEY를 설정하세요. "
            "API 키는 https://opendart.fss.or.kr 에서 발급받을 수 있습니다."
        )
    return key


async def _dart_request(endpoint: str, params: dict) -> dict:
    """DART API에 GET 요청을 보내고 JSON 응답을 반환합니다."""
    params["crtfc_key"] = _get_api_key()
    url = f"{DART_BASE_URL}/{endpoint}.json"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def _dart_request_binary(endpoint: str, params: dict) -> bytes:
    """DART API에 GET 요청을 보내고 바이너리(ZIP) 응답을 반환합니다."""
    params["crtfc_key"] = _get_api_key()
    url = f"{DART_BASE_URL}/{endpoint}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.content


def _handle_error(e: Exception) -> str:
    if isinstance(e, ValueError):
        return f"설정 오류: {e}"
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 400:
            return "오류: 잘못된 요청입니다. 파라미터를 확인하세요."
        if code == 401:
            return "오류: API 키가 유효하지 않습니다."
        if code == 429:
            return "오류: 요청 한도를 초과했습니다. 잠시 후 다시 시도하세요."
        return f"오류: API 요청 실패 (HTTP {code})"
    if isinstance(e, httpx.TimeoutException):
        return "오류: 요청 시간이 초과되었습니다. 다시 시도하세요."
    return f"오류: {type(e).__name__}: {e}"


def _format_result(data: dict) -> str:
    status = data.get("status", "")
    message = data.get("message", "")
    if status != "000":
        return f"DART API 오류 [{status}]: {message}"
    return json.dumps(data, ensure_ascii=False, indent=2)


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class SearchDisclosuresInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corp_code:        Optional[str] = Field(None, description="기업 고유번호 8자리. 미입력시 전체 기업 조회", max_length=8)
    bgn_de:           Optional[str] = Field(None, description="검색 시작일 (YYYYMMDD). corp_code 없을 때 최대 3개월 범위", pattern=r"^\d{8}$")
    end_de:           Optional[str] = Field(None, description="검색 종료일 (YYYYMMDD). 미입력시 현재일")
    last_reprt_at:    Optional[str] = Field(None, description="최종보고서만 검색 여부: Y 또는 N (기본값 N)", pattern=r"^[YN]$")
    pblntf_ty:        Optional[DisclosureType] = Field(None, description="공시 유형 (A:정기, B:주요사항, C:발행, D:지분, E:기업지배구조, F:펀드, G:증권신고, H:의결권대리, I:자산유동화, J:거래소)")
    corp_cls:         Optional[CorpClass] = Field(None, description="법인 구분 (Y:유가, K:코스닥, N:코넥스, E:기타)")
    page_no:          Optional[int] = Field(1, description="페이지 번호 (기본값 1)", ge=1)
    page_count:       Optional[int] = Field(20, description="페이지당 건수 (1-100, 기본값 20)", ge=1, le=100)


class CorpCodeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corp_code: str = Field(..., description="기업 고유번호 8자리 (dart_get_company_codes 또는 dart_search_disclosures로 조회 가능)", min_length=8, max_length=8)


class PeriodicReportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corp_code:   str = Field(..., description="기업 고유번호 8자리", min_length=8, max_length=8)
    bsns_year:   str = Field(..., description="사업연도 4자리 (2015년 이후)", min_length=4, max_length=4, pattern=r"^\d{4}$")
    reprt_code:  ReportCode = Field(..., description="보고서 코드 (11013:1분기, 11012:반기, 11014:3분기, 11011:사업보고서)")


class MultiCorpPeriodicReportInput(BaseModel):
    """다중회사 조회용 - corp_code에 쉼표로 구분된 여러 기업 코드 허용"""
    model_config = ConfigDict(str_strip_whitespace=True)
    corp_code:   str = Field(..., description="기업 고유번호 8자리, 여러 기업은 쉼표로 구분 (예: '00126380,00401731', 최대 100개)", min_length=8)
    bsns_year:   str = Field(..., description="사업연도 4자리 (2015년 이후)", min_length=4, max_length=4, pattern=r"^\d{4}$")
    reprt_code:  ReportCode = Field(..., description="보고서 코드 (11013:1분기, 11012:반기, 11014:3분기, 11011:사업보고서)")


class DateRangeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corp_code: str = Field(..., description="기업 고유번호 8자리", min_length=8, max_length=8)
    bgn_de:    str = Field(..., description="시작일 (YYYYMMDD, 2015년 이후)", pattern=r"^\d{8}$")
    end_de:    str = Field(..., description="종료일 (YYYYMMDD)", pattern=r"^\d{8}$")


class DocumentInput(BaseModel):
    rcept_no: str = Field(..., description="접수번호 14자리 (dart_search_disclosures 결과의 rcept_no)", min_length=14, max_length=14)


class FullFinancialsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corp_code:   str = Field(..., description="기업 고유번호 8자리", min_length=8, max_length=8)
    bsns_year:   str = Field(..., description="사업연도 4자리 (2015년 이후)", min_length=4, max_length=4, pattern=r"^\d{4}$")
    reprt_code:  ReportCode = Field(..., description="보고서 코드")
    fs_div:      FinancialStatementDiv = Field(..., description="재무제표 구분 (OFS:별도, CFS:연결)")


class XbrlFilesInput(BaseModel):
    rcept_no:   str = Field(..., description="접수번호 14자리", min_length=14, max_length=14)
    reprt_code: ReportCode = Field(..., description="보고서 코드")


class XbrlTaxonomyInput(BaseModel):
    sj_div: XbrlStatementDiv = Field(..., description="재무제표 구분 코드 (BS1:재무상태표연결, BS2:재무상태표별도, IS1:손익연결, IS2:손익별도, CIS1:포괄손익연결, CIS2:포괄손익별도, CF1:현금흐름연결, CF2:현금흐름별도, SCE1:자본변동연결, SCE2:자본변동별도)")


class FinancialIndexInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corp_code:    str = Field(..., description="기업 고유번호 8자리", min_length=8, max_length=8)
    bsns_year:    str = Field(..., description="사업연도 4자리", min_length=4, max_length=4, pattern=r"^\d{4}$")
    reprt_code:   ReportCode = Field(..., description="보고서 코드")
    idx_cl_code:  FinancialIndexCode = Field(..., description="지표 분류 (M210000:안정성, M220000:수익성, M230000:성장성, M240000:활동성)")


class MultiCorpFinancialIndexInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corp_code:    str = Field(..., description="기업 고유번호 8자리 (여러 기업은 쉼표로 구분, 예: '00126380,00164779')", min_length=8)
    bsns_year:    str = Field(..., description="사업연도 4자리", min_length=4, max_length=4, pattern=r"^\d{4}$")
    reprt_code:   ReportCode = Field(..., description="보고서 코드")
    idx_cl_code:  FinancialIndexCode = Field(..., description="지표 분류 (M210000:안정성, M220000:수익성, M230000:성장성, M240000:활동성)")


# ─── DS001: 공시정보 ──────────────────────────────────────────────────────────

@mcp.tool(
    name="dart_search_disclosures",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def dart_search_disclosures(params: SearchDisclosuresInput) -> str:
    """DART 공시 검색 (DS001).

    공시 유형별, 기업별, 날짜별 등 다양한 조건으로 공시보고서를 검색합니다.
    corp_code 없이 조회할 경우 날짜 범위는 최대 3개월입니다.

    Returns:
        JSON with fields:
        - total_count: 총 건수
        - list[]: corp_cls, corp_name, corp_code, stock_code, report_nm, rcept_no, flr_nm, rcept_dt, rm
    """
    try:
        p: dict = {}
        if params.corp_code:      p["corp_code"] = params.corp_code
        if params.bgn_de:         p["bgn_de"] = params.bgn_de
        if params.end_de:         p["end_de"] = params.end_de
        if params.last_reprt_at:  p["last_reprt_at"] = params.last_reprt_at
        if params.pblntf_ty:      p["pblntf_ty"] = params.pblntf_ty.value
        if params.corp_cls:       p["corp_cls"] = params.corp_cls.value
        if params.page_no:        p["page_no"] = str(params.page_no)
        if params.page_count:     p["page_count"] = str(params.page_count)
        data = await _dart_request("list", p)
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="dart_get_company_info",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def dart_get_company_info(params: CorpCodeInput) -> str:
    """기업 개황 조회 (DS001).

    DART에 등록된 기업의 기본 정보를 조회합니다.
    기업명, 대표이사, 주소, 홈페이지, 업종코드, 설립일, 결산월 등을 반환합니다.

    Returns:
        JSON with: corp_name, corp_name_eng, stock_name, stock_code, ceo_nm, corp_cls,
                   jurir_no, bizr_no, adres, hm_url, ir_url, phn_no, fax_no,
                   induty_code, est_dt, acc_mt
    """
    try:
        data = await _dart_request("company", {"corp_code": params.corp_code})
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="dart_get_company_codes",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def dart_get_company_codes() -> str:
    """DART 등록 기업 고유번호 목록 다운로드 안내 (DS001).

    DART에 공시 의무가 있는 모든 기업의 고유번호, 기업명, 종목코드 목록을
    ZIP 파일로 제공합니다.

    Returns:
        ZIP 파일 다운로드 URL과 사용 방법 안내 (실제 데이터는 직접 다운로드 필요)
    """
    key = _get_api_key()
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={key}"
    return json.dumps({
        "description": "DART 등록 기업 고유번호 목록 (ZIP 파일)",
        "download_url": url,
        "format": "ZIP (내부에 XML 파일 포함)",
        "fields": ["corp_code(8자리)", "corp_name", "stock_code(6자리, 상장사)", "modify_date(최종변경일)"],
        "usage": "ZIP 파일을 다운로드하여 압축 해제 후 XML에서 고유번호를 확인하세요."
    }, ensure_ascii=False, indent=2)


@mcp.tool(
    name="dart_get_document",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def dart_get_document(params: DocumentInput) -> str:
    """공시서류 원본 파일 다운로드 안내 (DS001).

    접수번호(rcept_no)를 이용해 공시서류 원본(ZIP) 파일을 제공합니다.
    dart_search_disclosures 결과의 rcept_no를 사용하세요.

    Returns:
        ZIP 파일 다운로드 URL 안내
    """
    key = _get_api_key()
    url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={key}&rcept_no={params.rcept_no}"
    return json.dumps({
        "description": "공시서류 원본 파일 (ZIP)",
        "download_url": url,
        "rcept_no": params.rcept_no,
        "format": "ZIP (내부에 공시서류 XML/HTML 파일 포함)",
        "usage": "ZIP 파일을 다운로드하여 압축 해제 후 공시서류를 확인하세요."
    }, ensure_ascii=False, indent=2)


# ─── DS002: 정기보고서 주요정보 ───────────────────────────────────────────────

async def _periodic_report(endpoint: str, params: PeriodicReportInput) -> str:
    try:
        data = await _dart_request(endpoint, {
            "corp_code":  params.corp_code,
            "bsns_year":  params.bsns_year,
            "reprt_code": params.reprt_code.value,
        })
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(name="dart_get_capital_changes", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_capital_changes(params: PeriodicReportInput) -> str:
    """증자(감자) 현황 조회 (DS002). 정기보고서에서 주식 증자 및 감자 현황을 조회합니다."""
    return await _periodic_report("irdsSttus", params)


@mcp.tool(name="dart_get_dividend_info", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_dividend_info(params: PeriodicReportInput) -> str:
    """배당에 관한 사항 조회 (DS002). 정기보고서에서 배당 정책 및 배당금 정보를 조회합니다."""
    return await _periodic_report("alotMatter", params)


@mcp.tool(name="dart_get_treasury_stock_status", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_treasury_stock_status(params: PeriodicReportInput) -> str:
    """자기주식 취득 및 처분 현황 조회 (DS002). 정기보고서에서 자기주식 취득·처분 현황을 조회합니다."""
    return await _periodic_report("tesstkAcqsDspsSttus", params)


@mcp.tool(name="dart_get_major_shareholders", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_major_shareholders(params: PeriodicReportInput) -> str:
    """최대주주 현황 조회 (DS002). 정기보고서에서 최대주주 및 특수관계인 주식 보유 현황을 조회합니다."""
    return await _periodic_report("hyslrSttus", params)


@mcp.tool(name="dart_get_major_shareholder_changes", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_major_shareholder_changes(params: PeriodicReportInput) -> str:
    """최대주주 변동현황 조회 (DS002). 정기보고서에서 최대주주 변동 이력을 조회합니다."""
    return await _periodic_report("hyslrChgSttus", params)


@mcp.tool(name="dart_get_minority_shareholders", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_minority_shareholders(params: PeriodicReportInput) -> str:
    """소액주주 현황 조회 (DS002). 정기보고서에서 소액주주 수 및 보유 비율을 조회합니다."""
    return await _periodic_report("mrhlSttus", params)


@mcp.tool(name="dart_get_executives", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_executives(params: PeriodicReportInput) -> str:
    """임원 현황 조회 (DS002). 정기보고서에서 등기·미등기 임원 현황을 조회합니다."""
    return await _periodic_report("exctvSttus", params)


@mcp.tool(name="dart_get_employees", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_employees(params: PeriodicReportInput) -> str:
    """직원 현황 조회 (DS002). 정기보고서에서 정규직·계약직 직원 수 및 평균 급여를 조회합니다."""
    return await _periodic_report("empSttus", params)


@mcp.tool(name="dart_get_individual_compensation_5b", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_individual_compensation_5b(params: PeriodicReportInput) -> str:
    """이사·감사의 개인별 보수현황(5억원 이상) 조회 (DS002). 연간 보수 5억원 이상 이사·감사의 개인별 보수를 조회합니다."""
    return await _periodic_report("hmvAuditIndvdlBySttus", params)


@mcp.tool(name="dart_get_total_executive_compensation", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_total_executive_compensation(params: PeriodicReportInput) -> str:
    """이사·감사 전체 보수현황(보수지급금액) 조회 (DS002). 이사·감사 전체 보수 지급 현황을 조회합니다."""
    return await _periodic_report("hmvAuditAllSttus", params)


@mcp.tool(name="dart_get_top5_compensation", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_top5_compensation(params: PeriodicReportInput) -> str:
    """개인별 보수지급 금액(5억이상 상위5인) 조회 (DS002). 5억원 이상 보수 수령자 상위 5인의 개인별 보수를 조회합니다."""
    return await _periodic_report("indvdlByPay", params)


@mcp.tool(name="dart_get_investments_in_other_corps", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_investments_in_other_corps(params: PeriodicReportInput) -> str:
    """타법인 출자현황 조회 (DS002). 정기보고서에서 타법인에 대한 출자 및 투자 현황을 조회합니다."""
    return await _periodic_report("otrCprInvstmntSttus", params)


@mcp.tool(name="dart_get_total_shares", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_total_shares(params: PeriodicReportInput) -> str:
    """주식의 총수 현황 조회 (DS002). 발행주식 총수, 자기주식 수 등 주식 현황을 조회합니다."""
    return await _periodic_report("stockTotqySttus", params)


@mcp.tool(name="dart_get_debt_securities_issuance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_debt_securities_issuance(params: PeriodicReportInput) -> str:
    """채무증권 발행실적 조회 (DS002). 채권, 어음 등 채무증권 발행 실적을 조회합니다."""
    return await _periodic_report("detScritsIsuAcmslt", params)


@mcp.tool(name="dart_get_cp_balance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_cp_balance(params: PeriodicReportInput) -> str:
    """기업어음증권 미상환 잔액 조회 (DS002). 기업어음(CP) 미상환 잔액 현황을 조회합니다."""
    return await _periodic_report("entrprsBilScritsNrdmpBlce", params)


@mcp.tool(name="dart_get_short_term_bond_balance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_short_term_bond_balance(params: PeriodicReportInput) -> str:
    """단기사채 미상환 잔액 조회 (DS002). 단기사채 미상환 잔액 현황을 조회합니다."""
    return await _periodic_report("srtpdPsndbtNrdmpBlce", params)


@mcp.tool(name="dart_get_corporate_bond_balance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_corporate_bond_balance(params: PeriodicReportInput) -> str:
    """회사채 미상환 잔액 조회 (DS002). 회사채 미상환 잔액 현황을 조회합니다."""
    return await _periodic_report("cprndNrdmpBlce", params)


@mcp.tool(name="dart_get_hybrid_securities_balance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_hybrid_securities_balance(params: PeriodicReportInput) -> str:
    """신종자본증권 미상환 잔액 조회 (DS002). 신종자본증권(코코본드 등) 미상환 잔액을 조회합니다."""
    return await _periodic_report("newCaplScritsNrdmpBlce", params)


@mcp.tool(name="dart_get_contingent_capital_balance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_contingent_capital_balance(params: PeriodicReportInput) -> str:
    """조건부 자본증권 미상환 잔액 조회 (DS002). 조건부 자본증권 미상환 잔액 현황을 조회합니다."""
    return await _periodic_report("cndlCaplScritsNrdmpBlce", params)


@mcp.tool(name="dart_get_audit_opinion", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_audit_opinion(params: PeriodicReportInput) -> str:
    """회계감사인 명칭 및 감사의견 조회 (DS002). 외부 감사인 정보와 감사의견(적정/한정/부적정/의견거절)을 조회합니다."""
    return await _periodic_report("accnutAdtorNmNdAdtOpinion", params)


@mcp.tool(name="dart_get_audit_service_contract", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_audit_service_contract(params: PeriodicReportInput) -> str:
    """감사용역 체결현황 조회 (DS002). 외부감사 용역 계약 체결 현황을 조회합니다."""
    return await _periodic_report("adtServcCnclsSttus", params)


@mcp.tool(name="dart_get_non_audit_service_contract", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_non_audit_service_contract(params: PeriodicReportInput) -> str:
    """회계감사인과의 비감사용역 계약체결 현황 조회 (DS002). 회계감사인과 체결한 비감사 컨설팅 등 용역 현황을 조회합니다."""
    return await _periodic_report("accnutAdtorNonAdtServcCnclsSttus", params)


@mcp.tool(name="dart_get_outside_directors", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_outside_directors(params: PeriodicReportInput) -> str:
    """사외이사 및 그 변동현황 조회 (DS002). 사외이사 선임·해임 등 변동현황을 조회합니다."""
    return await _periodic_report("outcmpnyDrctrNdChangeSttus", params)


@mcp.tool(name="dart_get_unregistered_exec_compensation", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_unregistered_exec_compensation(params: PeriodicReportInput) -> str:
    """미등기임원 보수현황 조회 (DS002). 미등기 임원의 보수 현황을 조회합니다."""
    return await _periodic_report("unrstExctvMendngSttus", params)


@mcp.tool(name="dart_get_compensation_shareholder_approval", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_compensation_shareholder_approval(params: PeriodicReportInput) -> str:
    """이사·감사 전체 보수현황(주주총회 승인금액) 조회 (DS002). 주주총회에서 승인된 이사·감사 보수 한도를 조회합니다."""
    return await _periodic_report("drctrAdtAllMendngSttusGmtsckConfmAmount", params)


@mcp.tool(name="dart_get_compensation_by_type", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_compensation_by_type(params: PeriodicReportInput) -> str:
    """이사·감사 전체 보수현황(보수지급금액 - 유형별) 조회 (DS002). 이사·감사 보수를 급여, 상여 등 유형별로 조회합니다."""
    return await _periodic_report("drctrAdtAllMendngSttusMendngPymntamtTyCl", params)


@mcp.tool(name="dart_get_public_offering_fund_usage", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_public_offering_fund_usage(params: PeriodicReportInput) -> str:
    """공모자금의 사용내역 조회 (DS002). 공모를 통해 조달한 자금의 사용 내역을 조회합니다."""
    return await _periodic_report("pssrpCptalUseDtls", params)


@mcp.tool(name="dart_get_private_placement_fund_usage", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_private_placement_fund_usage(params: PeriodicReportInput) -> str:
    """사모자금의 사용내역 조회 (DS002). 사모를 통해 조달한 자금의 사용 내역을 조회합니다."""
    return await _periodic_report("prvsrpCptalUseDtls", params)


# ─── DS003: 재무정보 ──────────────────────────────────────────────────────────

@mcp.tool(name="dart_get_single_company_accounts", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_single_company_accounts(params: PeriodicReportInput) -> str:
    """단일회사 주요계정 조회 (DS003).

    상장법인 및 주요 비상장법인의 재무상태표·손익계산서 주요 계정을 조회합니다.
    당기, 전기, 전전기 금액을 비교 조회할 수 있습니다.

    Returns:
        JSON with list: rcept_no, bsns_year, stock_code, account_nm, fs_div, sj_div,
                        thstrm_amount, frmtrm_amount, bfefrmtrm_amount
    """
    try:
        data = await _dart_request("fnlttSinglAcnt", {
            "corp_code":  params.corp_code,
            "bsns_year":  params.bsns_year,
            "reprt_code": params.reprt_code.value,
        })
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(name="dart_get_multi_company_accounts", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_multi_company_accounts(params: MultiCorpPeriodicReportInput) -> str:
    """다중회사 주요계정 조회 (DS003).

    여러 기업의 재무상태표·손익계산서 주요 계정을 한번에 조회합니다.
    corp_code에 최대 100개 기업 고유번호를 쉼표로 구분하여 입력하세요.

    Returns:
        JSON with list: 각 기업의 주요 재무 계정 정보
    """
    try:
        data = await _dart_request("fnlttMultiAcnt", {
            "corp_code":  params.corp_code,
            "bsns_year":  params.bsns_year,
            "reprt_code": params.reprt_code.value,
        })
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(name="dart_get_single_company_full_financials", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_single_company_full_financials(params: FullFinancialsInput) -> str:
    """단일회사 전체 재무제표 조회 (DS003).

    재무상태표, 손익계산서, 현금흐름표, 자본변동표 등 전체 재무제표를 조회합니다.
    별도(OFS) 또는 연결(CFS) 재무제표를 선택할 수 있습니다.

    Returns:
        JSON with list: 전체 재무제표 계정 및 금액
    """
    try:
        data = await _dart_request("fnlttSinglAcntAll", {
            "corp_code":  params.corp_code,
            "bsns_year":  params.bsns_year,
            "reprt_code": params.reprt_code.value,
            "fs_div":     params.fs_div.value,
        })
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(name="dart_get_xbrl_files", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_xbrl_files(params: XbrlFilesInput) -> str:
    """재무제표 원본파일(XBRL) 다운로드 안내 (DS003).

    공시 접수번호와 보고서 코드로 XBRL 재무제표 원본 파일 다운로드 URL을 제공합니다.

    Returns:
        ZIP 파일 다운로드 URL 안내
    """
    key = _get_api_key()
    url = (
        f"https://opendart.fss.or.kr/api/fnlttXbrl.xml"
        f"?crtfc_key={key}&rcept_no={params.rcept_no}&reprt_code={params.reprt_code.value}"
    )
    return json.dumps({
        "description": "XBRL 재무제표 원본 파일 (ZIP)",
        "download_url": url,
        "rcept_no": params.rcept_no,
        "reprt_code": params.reprt_code.value,
        "format": "ZIP (내부에 XBRL 파일 포함)",
    }, ensure_ascii=False, indent=2)


@mcp.tool(name="dart_get_xbrl_taxonomy", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_xbrl_taxonomy(params: XbrlTaxonomyInput) -> str:
    """XBRL 택사노미 재무제표 양식 조회 (DS003).

    IFRS 기반 XBRL 재무제표 표준 계정 구조를 조회합니다.
    재무제표 계정 코드와 한국어 명칭을 확인할 수 있습니다.

    Returns:
        JSON with: 계정 코드, 계정명, 계층 구조
    """
    try:
        data = await _dart_request("xbrlTaxonomy", {"sj_div": params.sj_div.value})
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(name="dart_get_single_company_financial_index", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_single_company_financial_index(params: FinancialIndexInput) -> str:
    """단일회사 주요 재무지표 조회 (DS003).

    안정성, 수익성, 성장성, 활동성 지표를 조회합니다.
    - M210000: 안정성 (부채비율, 유동비율 등)
    - M220000: 수익성 (ROE, ROA, 영업이익률 등)
    - M230000: 성장성 (매출증가율, 영업이익증가율 등)
    - M240000: 활동성 (총자산회전율 등)

    Returns:
        JSON with list: 재무 지표명, 당기/전기/전전기 값
    """
    try:
        data = await _dart_request("fnlttSinglIndx", {
            "corp_code":   params.corp_code,
            "bsns_year":   params.bsns_year,
            "reprt_code":  params.reprt_code.value,
            "idx_cl_code": params.idx_cl_code.value,
        })
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(name="dart_get_multi_company_financial_index", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_multi_company_financial_index(params: MultiCorpFinancialIndexInput) -> str:
    """다중회사 주요 재무지표 조회 (DS003).

    여러 기업의 재무지표를 한번에 조회합니다.
    corp_code에 기업 고유번호를 쉼표로 구분하여 입력하세요.

    Returns:
        JSON with list: 각 기업의 재무 지표
    """
    try:
        data = await _dart_request("fnlttCmpnyIndx", {
            "corp_code":   params.corp_code,
            "bsns_year":   params.bsns_year,
            "reprt_code":  params.reprt_code.value,
            "idx_cl_code": params.idx_cl_code.value,
        })
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


# ─── DS004: 지분공시 ──────────────────────────────────────────────────────────

@mcp.tool(name="dart_get_large_shareholder_report", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_large_shareholder_report(params: CorpCodeInput) -> str:
    """대량보유 상황보고 조회 (DS004).

    5% 이상 주식 대량보유자의 보고 내역을 조회합니다.
    보유 주식 수, 보유 비율, 변동 내역 등을 확인할 수 있습니다.

    Returns:
        JSON with list: rcept_no, rcept_dt, corp_code, corp_name, report_tp,
                        repror, stkqy, stkqy_irds, stkrt, stkrt_irds, report_resn
    """
    try:
        data = await _dart_request("majorstock", {"corp_code": params.corp_code})
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(name="dart_get_officer_shareholder_report", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_officer_shareholder_report(params: CorpCodeInput) -> str:
    """임원·주요주주 소유보고 조회 (DS004).

    임원 및 주요주주(10% 이상)의 주식 소유 현황 보고 내역을 조회합니다.

    Returns:
        JSON with list: 임원/주요주주별 주식 보유 및 변동 현황
    """
    try:
        data = await _dart_request("elestock", {"corp_code": params.corp_code})
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


# ─── DS005: 주요사항보고서 ────────────────────────────────────────────────────

async def _major_report(endpoint: str, params: DateRangeInput) -> str:
    try:
        data = await _dart_request(endpoint, {
            "corp_code": params.corp_code,
            "bgn_de":    params.bgn_de,
            "end_de":    params.end_de,
        })
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(name="dart_get_asset_transfer_putback", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_asset_transfer_putback(params: DateRangeInput) -> str:
    """자산양수도(기타), 풋백옵션 주요사항보고 조회 (DS005). 자산 양수도 및 풋백옵션 계약 공시를 조회합니다."""
    return await _major_report("astInhtrfEtcPtbkOpt", params)


@mcp.tool(name="dart_get_default_occurrence", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_default_occurrence(params: DateRangeInput) -> str:
    """부도발생 주요사항보고 조회 (DS005). 기업 부도 발생 공시를 조회합니다."""
    return await _major_report("dfOcr", params)


@mcp.tool(name="dart_get_business_suspension", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_business_suspension(params: DateRangeInput) -> str:
    """영업정지 주요사항보고 조회 (DS005). 영업 정지 및 허가 취소 공시를 조회합니다."""
    return await _major_report("bsnSp", params)


@mcp.tool(name="dart_get_rehabilitation_filing", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_rehabilitation_filing(params: DateRangeInput) -> str:
    """회생절차 개시신청 주요사항보고 조회 (DS005). 법정관리(회생절차) 신청 공시를 조회합니다."""
    return await _major_report("ctrcvsBgrq", params)


@mcp.tool(name="dart_get_dissolution_reason", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_dissolution_reason(params: DateRangeInput) -> str:
    """해산사유 발생 주요사항보고 조회 (DS005). 기업 해산사유 발생 공시를 조회합니다."""
    return await _major_report("dsRsOcr", params)


@mcp.tool(name="dart_get_paid_in_capital_increase", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_paid_in_capital_increase(params: DateRangeInput) -> str:
    """유상증자 결정 주요사항보고 조회 (DS005). 유상증자 결정 공시를 조회합니다."""
    return await _major_report("piicDecsn", params)


@mcp.tool(name="dart_get_free_share_issuance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_free_share_issuance(params: DateRangeInput) -> str:
    """무상증자 결정 주요사항보고 조회 (DS005). 무상증자 결정 공시를 조회합니다."""
    return await _major_report("fricDecsn", params)


@mcp.tool(name="dart_get_paid_free_capital_increase", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_paid_free_capital_increase(params: DateRangeInput) -> str:
    """유무상증자 결정 주요사항보고 조회 (DS005). 유상·무상 동시 증자 결정 공시를 조회합니다."""
    return await _major_report("pifricDecsn", params)


@mcp.tool(name="dart_get_capital_reduction", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_capital_reduction(params: DateRangeInput) -> str:
    """감자 결정 주요사항보고 조회 (DS005). 주식 감자(자본감소) 결정 공시를 조회합니다."""
    return await _major_report("crDecsn", params)


@mcp.tool(name="dart_get_creditor_bank_management_start", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_creditor_bank_management_start(params: DateRangeInput) -> str:
    """채권은행 등의 관리절차 개시 주요사항보고 조회 (DS005). 워크아웃 등 채권은행 관리절차 개시 공시를 조회합니다."""
    return await _major_report("bnkMngtPcbg", params)


@mcp.tool(name="dart_get_lawsuit_filing", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_lawsuit_filing(params: DateRangeInput) -> str:
    """소송 등의 제기 주요사항보고 조회 (DS005). 중요 소송 제기 공시를 조회합니다."""
    return await _major_report("lwstLg", params)


@mcp.tool(name="dart_get_overseas_listing_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_overseas_listing_decision(params: DateRangeInput) -> str:
    """해외 증권시장 주권등 상장 결정 주요사항보고 조회 (DS005). 해외 증권시장 상장 결정 공시를 조회합니다."""
    return await _major_report("ovLstDecsn", params)


@mcp.tool(name="dart_get_overseas_delisting_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_overseas_delisting_decision(params: DateRangeInput) -> str:
    """해외 증권시장 주권등 상장폐지 결정 주요사항보고 조회 (DS005). 해외 증권시장 상장폐지 결정 공시를 조회합니다."""
    return await _major_report("ovDlstDecsn", params)


@mcp.tool(name="dart_get_overseas_listing", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_overseas_listing(params: DateRangeInput) -> str:
    """해외 증권시장 주권등 상장 주요사항보고 조회 (DS005). 해외 증권시장 실제 상장 공시를 조회합니다."""
    return await _major_report("ovLst", params)


@mcp.tool(name="dart_get_overseas_delisting", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_overseas_delisting(params: DateRangeInput) -> str:
    """해외 증권시장 주권등 상장폐지 주요사항보고 조회 (DS005). 해외 증권시장 실제 상장폐지 공시를 조회합니다."""
    return await _major_report("ovDlst", params)


@mcp.tool(name="dart_get_convertible_bond_issuance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_convertible_bond_issuance(params: DateRangeInput) -> str:
    """전환사채권 발행결정 주요사항보고 조회 (DS005). CB(전환사채) 발행 결정 공시를 조회합니다."""
    return await _major_report("cvbdIsDecsn", params)


@mcp.tool(name="dart_get_warrant_bond_issuance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_warrant_bond_issuance(params: DateRangeInput) -> str:
    """신주인수권부사채권 발행결정 주요사항보고 조회 (DS005). BW(신주인수권부사채) 발행 결정 공시를 조회합니다."""
    return await _major_report("bdwtIsDecsn", params)


@mcp.tool(name="dart_get_exchangeable_bond_issuance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_exchangeable_bond_issuance(params: DateRangeInput) -> str:
    """교환사채권 발행결정 주요사항보고 조회 (DS005). EB(교환사채) 발행 결정 공시를 조회합니다."""
    return await _major_report("exbdIsDecsn", params)


@mcp.tool(name="dart_get_creditor_bank_management_stop", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_creditor_bank_management_stop(params: DateRangeInput) -> str:
    """채권은행 등의 관리절차 중단 주요사항보고 조회 (DS005). 워크아웃 종료 등 채권은행 관리절차 중단 공시를 조회합니다."""
    return await _major_report("bnkMngtPcsp", params)


@mcp.tool(name="dart_get_write_down_cocobd_issuance", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_write_down_cocobd_issuance(params: DateRangeInput) -> str:
    """상각형 조건부자본증권 발행결정 주요사항보고 조회 (DS005). 상각형 코코본드 발행 결정 공시를 조회합니다."""
    return await _major_report("wdCocobdIsDecsn", params)


@mcp.tool(name="dart_get_treasury_stock_acquisition_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_treasury_stock_acquisition_decision(params: DateRangeInput) -> str:
    """자기주식 취득 결정 주요사항보고 조회 (DS005). 자기주식 취득(자사주 매입) 결정 공시를 조회합니다."""
    return await _major_report("tsstkAqDecsn", params)


@mcp.tool(name="dart_get_treasury_stock_disposal_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_treasury_stock_disposal_decision(params: DateRangeInput) -> str:
    """자기주식 처분 결정 주요사항보고 조회 (DS005). 자기주식 처분(자사주 매각) 결정 공시를 조회합니다."""
    return await _major_report("tsstkDpDecsn", params)


@mcp.tool(name="dart_get_treasury_stock_trust_conclusion", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_treasury_stock_trust_conclusion(params: DateRangeInput) -> str:
    """자기주식취득 신탁계약 체결 결정 주요사항보고 조회 (DS005). 자기주식 취득 신탁계약 체결 공시를 조회합니다."""
    return await _major_report("tsstkAqTrctrCnsDecsn", params)


@mcp.tool(name="dart_get_treasury_stock_trust_termination", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_treasury_stock_trust_termination(params: DateRangeInput) -> str:
    """자기주식취득 신탁계약 해지 결정 주요사항보고 조회 (DS005). 자기주식 취득 신탁계약 해지 공시를 조회합니다."""
    return await _major_report("tsstkAqTrctrCcDecsn", params)


@mcp.tool(name="dart_get_business_acquisition_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_business_acquisition_decision(params: DateRangeInput) -> str:
    """영업양수 결정 주요사항보고 조회 (DS005). 타 기업 영업 양수 결정 공시를 조회합니다."""
    return await _major_report("bsnInhDecsn", params)


@mcp.tool(name="dart_get_business_transfer_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_business_transfer_decision(params: DateRangeInput) -> str:
    """영업양도 결정 주요사항보고 조회 (DS005). 자사 영업 양도 결정 공시를 조회합니다."""
    return await _major_report("bsnTrfDecsn", params)


@mcp.tool(name="dart_get_tangible_asset_acquisition_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_tangible_asset_acquisition_decision(params: DateRangeInput) -> str:
    """유형자산 양수 결정 주요사항보고 조회 (DS005). 유형자산 취득 결정 공시를 조회합니다."""
    return await _major_report("tgastInhDecsn", params)


@mcp.tool(name="dart_get_tangible_asset_transfer_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_tangible_asset_transfer_decision(params: DateRangeInput) -> str:
    """유형자산 양도 결정 주요사항보고 조회 (DS005). 유형자산 처분 결정 공시를 조회합니다."""
    return await _major_report("tgastTrfDecsn", params)


@mcp.tool(name="dart_get_other_corp_stock_acquisition", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_other_corp_stock_acquisition(params: DateRangeInput) -> str:
    """타법인 주식 및 출자증권 양수결정 주요사항보고 조회 (DS005). 타법인 주식 및 출자증권 취득 결정 공시를 조회합니다."""
    return await _major_report("otcprStkInvscrInhDecsn", params)


@mcp.tool(name="dart_get_other_corp_stock_transfer", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_other_corp_stock_transfer(params: DateRangeInput) -> str:
    """타법인 주식 및 출자증권 양도결정 주요사항보고 조회 (DS005). 타법인 주식 및 출자증권 처분 결정 공시를 조회합니다."""
    return await _major_report("otcprStkInvscrTrfDecsn", params)


@mcp.tool(name="dart_get_equity_bond_acquisition", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_equity_bond_acquisition(params: DateRangeInput) -> str:
    """주권 관련 사채권 양수 결정 주요사항보고 조회 (DS005). 주식 관련 사채(CB/BW/EB 등) 취득 결정 공시를 조회합니다."""
    return await _major_report("stkrtbdInhDecsn", params)


@mcp.tool(name="dart_get_equity_bond_transfer", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_equity_bond_transfer(params: DateRangeInput) -> str:
    """주권 관련 사채권 양도 결정 주요사항보고 조회 (DS005). 주식 관련 사채(CB/BW/EB 등) 처분 결정 공시를 조회합니다."""
    return await _major_report("stkrtbdTrfDecsn", params)


@mcp.tool(name="dart_get_merger_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_merger_decision(params: DateRangeInput) -> str:
    """회사합병 결정 주요사항보고 조회 (DS005). 기업 합병 결정 공시를 조회합니다."""
    return await _major_report("cmpMgDecsn", params)


@mcp.tool(name="dart_get_division_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_division_decision(params: DateRangeInput) -> str:
    """회사분할 결정 주요사항보고 조회 (DS005). 기업 분할(물적분할/인적분할) 결정 공시를 조회합니다."""
    return await _major_report("cmpDvDecsn", params)


@mcp.tool(name="dart_get_division_merger_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_division_merger_decision(params: DateRangeInput) -> str:
    """회사분할합병 결정 주요사항보고 조회 (DS005). 기업 분할합병 결정 공시를 조회합니다."""
    return await _major_report("cmpDvmgDecsn", params)


@mcp.tool(name="dart_get_stock_exchange_transfer_decision", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_stock_exchange_transfer_decision(params: DateRangeInput) -> str:
    """주식교환·이전 결정 주요사항보고 조회 (DS005). 주식의 포괄적 교환·이전 결정 공시를 조회합니다."""
    return await _major_report("stkExtrDecsn", params)


# ─── DS006: 증권신고서 ────────────────────────────────────────────────────────

async def _securities_report(endpoint: str, params: DateRangeInput) -> str:
    try:
        data = await _dart_request(endpoint, {
            "corp_code": params.corp_code,
            "bgn_de":    params.bgn_de,
            "end_de":    params.end_de,
        })
        return _format_result(data)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(name="dart_get_equity_securities_registration", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_equity_securities_registration(params: DateRangeInput) -> str:
    """지분증권 증권신고서 요약정보 조회 (DS006). 주식 공모 증권신고서의 요약 정보를 조회합니다."""
    return await _securities_report("estkRs", params)


@mcp.tool(name="dart_get_debt_securities_registration", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_debt_securities_registration(params: DateRangeInput) -> str:
    """채무증권 증권신고서 요약정보 조회 (DS006). 채권 공모 증권신고서의 요약 정보를 조회합니다."""
    return await _securities_report("bdRs", params)


@mcp.tool(name="dart_get_depositary_receipts_registration", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_depositary_receipts_registration(params: DateRangeInput) -> str:
    """증권예탁증권 증권신고서 요약정보 조회 (DS006). DR(증권예탁증권) 공모 증권신고서의 요약 정보를 조회합니다."""
    return await _securities_report("stkdpRs", params)


@mcp.tool(name="dart_get_merger_registration", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_merger_registration(params: DateRangeInput) -> str:
    """합병 증권신고서 요약정보 조회 (DS006). 합병 관련 증권신고서의 요약 정보를 조회합니다."""
    return await _securities_report("mgRs", params)


@mcp.tool(name="dart_get_comprehensive_stock_exchange_registration", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_comprehensive_stock_exchange_registration(params: DateRangeInput) -> str:
    """주식의포괄적교환·이전 증권신고서 요약정보 조회 (DS006). 주식의 포괄적 교환·이전 증권신고서의 요약 정보를 조회합니다."""
    return await _securities_report("extrRs", params)


@mcp.tool(name="dart_get_division_registration", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def dart_get_division_registration(params: DateRangeInput) -> str:
    """분할 증권신고서 요약정보 조회 (DS006). 회사 분할 관련 증권신고서의 요약 정보를 조회합니다."""
    return await _securities_report("dvRs", params)


# ─── 임원 이동 추적 (Executive Movement Tracking) ───────────────────────────

# 전체 기업 코드 목록 캐시 (메모리)
_corp_code_cache: Optional[list] = None


async def _load_corp_codes() -> list:
    """DART 전체 기업 고유번호 목록을 다운로드하여 캐시합니다."""
    global _corp_code_cache
    if _corp_code_cache is not None:
        return _corp_code_cache
    key = _get_api_key()
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, params={"crtfc_key": key})
        resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open(zf.namelist()[0]) as f:
            root = ET.parse(f).getroot()
            _corp_code_cache = [
                {
                    "corp_code":  item.findtext("corp_code", "").strip(),
                    "corp_name":  item.findtext("corp_name", "").strip(),
                    "stock_code": item.findtext("stock_code", "").strip(),
                    "modify_date": item.findtext("modify_date", "").strip(),
                }
                for item in root.findall(".//list")
                if item.findtext("corp_code", "").strip()
            ]
    return _corp_code_cache


async def _get_investments(corp_code: str, bsns_year: str) -> list:
    """특정 기업의 타법인 출자현황(자회사/관계사 이름 목록)을 반환합니다."""
    try:
        data = await _dart_request("otrCprInvstmntSttus", {
            "corp_code":  corp_code,
            "bsns_year":  bsns_year,
            "reprt_code": ReportCode.ANNUAL.value,
        })
        if data.get("status") == "000":
            return [inv.get("inv_prm", "").strip() for inv in data.get("list", [])
                    if inv.get("inv_prm", "").strip()]
        return []
    except Exception:
        return []


async def _find_parent_corp(corp_code: str, bsns_year: str, all_corps: list,
                             exclude_codes: set) -> Optional[dict]:
    """최대주주 현황에서 법인 최대주주(모회사)를 찾아 corp_code 매핑 후 반환합니다."""
    def _normalize(name: str) -> str:
        return (name.replace("주식회사", "").replace("(주)", "").replace("㈜", "")
                .replace(" ", "").replace(".", "").strip())

    try:
        data = await _dart_request("hyslrSttus", {
            "corp_code":  corp_code,
            "bsns_year":  bsns_year,
            "reprt_code": ReportCode.ANNUAL.value,
        })
        if data.get("status") != "000":
            return None
        for sh in data.get("list", []):
            if sh.get("relate") not in ("최대주주", "최대주주본인"):
                continue
            nm = sh.get("nm", "").strip()
            if not nm:
                continue
            # 법인 여부 판단
            if not any(kw in nm for kw in ["주식회사", "㈜", "(주)", "Inc", "Corp", "Ltd", "회사", "재단", "투자"]):
                continue
            nm_clean = _normalize(nm)
            # corp_code 매핑
            for c in all_corps:
                if c["corp_code"] in exclude_codes:
                    continue
                if _normalize(c["corp_name"]) == nm_clean or nm_clean in _normalize(c["corp_name"]):
                    return {"corp_code": c["corp_code"], "corp_name": c["corp_name"]}
    except Exception:
        pass
    return None


async def _collect_group_companies(
    source_corp_code: str,
    latest_year: str,
    all_corps: list,
    max_depth: int = 3,
) -> tuple:
    """
    그룹 계열사를 수집합니다.
    - source 기업의 자회사 (타법인출자현황)
    - source 기업의 모회사 → 그 모회사의 자회사들 (형제 계열사)
    - 모회사의 모회사까지 재귀적으로 탐색 (최대 max_depth 단계)
    Returns: (affiliate_names: set, parent_chain: list[dict])
    """
    affiliate_names: set = set()
    parent_chain: list = []
    visited_codes: set = {source_corp_code}

    def _normalize(name: str) -> str:
        return (name.replace("주식회사", "").replace("(주)", "").replace("㈜", "")
                .replace(" ", "").replace(".", "").strip())

    # 1. source 기업의 자회사 수집
    own_invs = await _get_investments(source_corp_code, latest_year)
    affiliate_names.update(own_invs)

    # 2. 부모 체인 재귀 탐색 (최대 max_depth)
    current_code = source_corp_code
    for _ in range(max_depth):
        parent = await _find_parent_corp(current_code, latest_year, all_corps, visited_codes)
        if not parent:
            break
        parent_code = parent["corp_code"]
        parent_chain.append(parent)
        visited_codes.add(parent_code)

        # 이 부모의 자회사(형제 계열사) 수집
        parent_invs = await _get_investments(parent_code, latest_year)
        affiliate_names.update(parent_invs)

        current_code = parent_code
        if not parent_invs:  # 더 이상 데이터 없으면 중단
            break

    return affiliate_names, parent_chain


async def _get_executives_for_year(corp_code: str, bsns_year: str, reprt_code: str) -> list:
    """특정 기업의 특정 연도 임원 현황을 조회합니다. 오류 시 빈 리스트 반환."""
    try:
        data = await _dart_request("exctvSttus", {
            "corp_code":  corp_code,
            "bsns_year":  bsns_year,
            "reprt_code": reprt_code,
        })
        if data.get("status") == "000":
            return data.get("list", [])
        return []
    except Exception:
        return []


class FindCompanyInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    keyword: str = Field(..., description="검색할 기업명 키워드 (예: 'SK하이닉스', 'SK', '삼성')", min_length=1)
    limit:   int = Field(default=20, description="반환할 최대 결과 수 (기본값 20)", ge=1, le=200)


class ExecutiveSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name:        str       = Field(..., description="검색할 임원 이름 (예: '정상록', '홍길동')", min_length=1)
    corp_codes:  List[str] = Field(..., description="검색할 기업 고유번호 목록 (예: ['00164779', '00126380'])")
    bsns_years:  List[str] = Field(..., description="검색할 사업연도 목록 (예: ['2020','2021','2022','2023','2024'])")
    reprt_code:  ReportCode = Field(default=ReportCode.ANNUAL, description="보고서 코드 (기본값: 11011 사업보고서)")


class TrackExecutiveInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name:             str        = Field(..., description="추적할 임원 이름 (예: '정상록')", min_length=1)
    source_corp_code: str        = Field(..., description="원래 소속 기업 고유번호 (예: SK하이닉스='00164779')", min_length=8, max_length=8)
    search_years:     List[str]  = Field(..., description="검색 연도 목록 (예: ['2020','2021','2022','2023','2024'])")
    affiliate_keywords: Optional[List[str]] = Field(
        None,
        description=(
            "관계사 검색용 키워드 목록. 미입력시 원래 기업의 타법인출자현황에서 자동으로 관계사를 찾습니다. "
            "여러 키워드를 함께 쓰면 더 광범위하게 검색합니다. "
            "예: ['SK', '에스케이'] (SK그룹 영문+한글 표기 모두 검색), ['LG', '엘지']"
        )
    )
    max_affiliates:   int = Field(default=50, description="검색할 최대 관계사 수 (기본값 50)", ge=1, le=200)


@mcp.tool(
    name="dart_find_company_by_name",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
)
async def dart_find_company_by_name(params: FindCompanyInput) -> str:
    """회사명 키워드로 DART 기업 고유번호(corp_code) 검색.

    11만여 개 전체 DART 등록 기업 중 키워드가 포함된 기업을 찾습니다.
    처음 호출 시 기업 목록 다운로드로 수십 초 소요될 수 있습니다.

    Returns:
        JSON list: [{corp_code, corp_name, stock_code, modify_date}, ...]
        - stock_code: 상장사만 6자리 종목코드 존재, 비상장사는 빈 문자열
    """
    try:
        companies = await _load_corp_codes()
        kw = params.keyword.strip()
        matches = [c for c in companies if kw in c["corp_name"]]
        matches = matches[:params.limit]
        return json.dumps({
            "keyword": kw,
            "total_matches": len([c for c in companies if kw in c["corp_name"]]),
            "count": len(matches),
            "list": matches,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="dart_search_executive_by_name",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def dart_search_executive_by_name(params: ExecutiveSearchInput) -> str:
    """여러 기업의 임원 현황에서 특정 이름을 가진 임원을 검색.

    지정한 기업 목록 × 연도 목록의 모든 조합에서 해당 인물을 검색하여
    재직 여부, 직책, 재임 기간, 상근/비상근 등 정보를 반환합니다.
    임원 퇴임 후 이동 경로를 추적할 때 활용합니다.

    Returns:
        JSON with results per (corp_code, year):
        {
            "name": "검색 이름",
            "findings": [
                {
                    "corp_code": str,
                    "corp_name": str,
                    "bsns_year": str,
                    "found": bool,
                    "executives": [
                        {
                            "nm": str,           # 이름
                            "ofcps": str,        # 직위
                            "rgist_exctv_at": str, # 등기여부
                            "fte_at": str,       # 상근여부
                            "chrg_job": str,     # 담당업무
                            "main_career": str,  # 주요 경력
                            "hffc_pd": str,      # 재임기간
                            "tenure_end_on": str # 임기만료일
                        }
                    ]
                }
            ],
            "summary": "발견된 (기업, 연도) 목록 요약"
        }
    """
    try:
        findings = []
        for corp_code in params.corp_codes:
            for year in params.bsns_years:
                execs = await _get_executives_for_year(corp_code, year, params.reprt_code.value)
                # 이름으로 검색 (부분 일치)
                matched = [
                    {
                        "nm":              e.get("nm", ""),
                        "ofcps":           e.get("ofcps", ""),
                        "rgist_exctv_at":  e.get("rgist_exctv_at", ""),
                        "fte_at":          e.get("fte_at", ""),
                        "chrg_job":        e.get("chrg_job", ""),
                        "main_career":     e.get("main_career", ""),
                        "hffc_pd":         e.get("hffc_pd", ""),
                        "tenure_end_on":   e.get("tenure_end_on", ""),
                        "corp_name":       e.get("corp_name", ""),
                    }
                    for e in execs
                    if params.name in e.get("nm", "")
                ]
                findings.append({
                    "corp_code": corp_code,
                    "corp_name": matched[0]["corp_name"] if matched else (execs[0].get("corp_name", corp_code) if execs else corp_code),
                    "bsns_year": year,
                    "found":     len(matched) > 0,
                    "executives": matched,
                })

        # 요약 생성
        found_list = [(f["corp_name"], f["bsns_year"]) for f in findings if f["found"]]
        if found_list:
            summary = f"'{params.name}' 발견: " + ", ".join(f"{cn}({yr})" for cn, yr in found_list)
        else:
            summary = f"'{params.name}'을(를) 검색한 모든 기업/연도에서 찾지 못했습니다."

        return json.dumps({
            "name":     params.name,
            "findings": findings,
            "summary":  summary,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="dart_track_executive_movement",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
)
async def dart_track_executive_movement(params: TrackExecutiveInput) -> str:
    """임원의 기업 간 이동 경로를 자동으로 추적.

    지정한 임원이 원래 기업에서 언제 사라지고, 어느 관계사로 이동했는지 자동으로 분석합니다.

    동작 방식 (자동 계열사 탐색):
    1. 원래 기업(source_corp_code)에서 해당 임원의 재직/퇴임 이력 조회
    2. 원래 기업의 최대주주 현황에서 법인 최대주주(모회사) 탐색
    3. 모회사의 타법인출자현황으로 그룹 계열사 목록 수집 (형제 계열사 포함)
    4. 원래 기업의 타법인출자현황으로 자회사 목록 추가 수집
    5. affiliate_keywords 제공 시 해당 키워드로 DART 전체 기업 추가 검색
    6. 수집된 모든 관계사에서 해당 임원 검색
    7. 이동 경로 타임라인 반환

    ※ 주의: DART exctvSttus API는 등기임원(이사회 구성원)만 조회됩니다.
       미등기임원(부사장, 전무, 상무 등)은 dart_search_disclosures로
       공시 원문을 검색하거나 별도 확인이 필요합니다.

    Returns:
        JSON with:
        {
            "name": str,
            "source_company": {corp_code, corp_name, history: [{bsns_year, found, role, chrg_job}]},
            "parent_company": {corp_code, corp_name} | null,
            "affiliates_searched_count": int,
            "affiliates_searched": [{corp_code, corp_name, source}],
            "found_at": [{corp_code, corp_name, bsns_year, role, chrg_job, main_career, hffc_pd}],
            "not_found_in": [corp_name, ...],
            "timeline": "이동 경로 요약 텍스트"
        }
    """
    try:
        _get_api_key()
        latest_year = max(params.search_years)

        # ── Step 1: 원래 기업 재직 이력 조회 ─────────────────────────────
        source_history = []
        source_corp_name = params.source_corp_code
        for year in params.search_years:
            execs = await _get_executives_for_year(params.source_corp_code, year, ReportCode.ANNUAL.value)
            if execs:
                source_corp_name = execs[0].get("corp_name", params.source_corp_code)
            matched = [e for e in execs if params.name in e.get("nm", "")]
            source_history.append({
                "bsns_year": year,
                "found":     len(matched) > 0,
                "role":      matched[0].get("ofcps", "") if matched else "",
                "chrg_job":  matched[0].get("chrg_job", "") if matched else "",
            })

        # ── Step 2~3: 그룹 계열사 수집 (모회사 재귀 탐색 + 자회사) ─────
        all_corps = await _load_corp_codes()
        affiliate_names, parent_chain = await _collect_group_companies(
            params.source_corp_code, latest_year, all_corps, max_depth=3
        )
        parent_company = parent_chain[0] if parent_chain else None

        # ── Step 4: 수집된 법인명들을 corp_code로 매핑 ───────────────────
        def _normalize_local(name: str) -> str:
            return (name.replace("주식회사", "").replace("(주)", "").replace("㈜", "")
                    .replace(" ", "").replace(".", "").strip())

        def _match_corp(raw_name: str, exclude: str = "") -> Optional[dict]:
            raw_clean = _normalize_local(raw_name)
            if len(raw_clean) < 2:
                return None
            for c in all_corps:
                if c["corp_name"] == raw_name and c["corp_code"] != exclude:
                    return c
            for c in all_corps:
                if _normalize_local(c["corp_name"]) == raw_clean and c["corp_code"] != exclude:
                    return c
            for c in all_corps:
                cn = _normalize_local(c["corp_name"])
                if (raw_clean in cn or cn in raw_clean) and c["corp_code"] != exclude:
                    return c
            return None

        affiliate_corp_list: list = []
        seen_codes: set = {params.source_corp_code}

        def _add_affiliate(raw_name: str, source_label: str):
            c = _match_corp(raw_name, params.source_corp_code)
            if c and c["corp_code"] not in seen_codes:
                seen_codes.add(c["corp_code"])
                affiliate_corp_list.append({
                    "corp_code": c["corp_code"],
                    "corp_name": c["corp_name"],
                    "source": source_label,
                })

        # 모회사 체인 추가
        for i, p in enumerate(parent_chain):
            if p["corp_code"] not in seen_codes:
                seen_codes.add(p["corp_code"])
                label = "모회사" if i == 0 else f"상위모회사(+{i})"
                affiliate_corp_list.append({**p, "source": label})

        # 모회사 체인에서 수집한 계열사들
        for n in affiliate_names:
            _add_affiliate(n, "계열사")

        # ── Step 5: affiliate_keywords 키워드 검색 추가 ───────────────────
        if params.affiliate_keywords:
            for kw in params.affiliate_keywords:
                for c in all_corps:
                    if kw in c["corp_name"] and c["corp_code"] not in seen_codes:
                        seen_codes.add(c["corp_code"])
                        affiliate_corp_list.append({
                            "corp_code": c["corp_code"],
                            "corp_name": c["corp_name"],
                            "source": f"키워드({kw})",
                        })

        # 최대 검색 수 제한
        affiliate_corp_list = affiliate_corp_list[:params.max_affiliates]

        # ── Step 6: 관계사에서 임원 검색 ─────────────────────────────────
        found_at = []
        not_found_affiliates = []

        for aff in affiliate_corp_list:
            person_found = False
            for year in params.search_years:
                execs = await _get_executives_for_year(aff["corp_code"], year, ReportCode.ANNUAL.value)
                matched = [e for e in execs if params.name in e.get("nm", "")]
                if matched:
                    found_at.append({
                        "corp_code":   aff["corp_code"],
                        "corp_name":   aff["corp_name"],
                        "source":      aff["source"],
                        "bsns_year":   year,
                        "role":        matched[0].get("ofcps", ""),
                        "chrg_job":    matched[0].get("chrg_job", ""),
                        "main_career": matched[0].get("main_career", ""),
                        "hffc_pd":     matched[0].get("hffc_pd", ""),
                    })
                    person_found = True
            if not person_found:
                not_found_affiliates.append(aff["corp_name"])

        # ── Step 7: 타임라인 텍스트 생성 ─────────────────────────────────
        timeline_parts = []
        present_years = [h["bsns_year"] for h in source_history if h["found"]]
        absent_years  = [h["bsns_year"] for h in source_history if not h["found"]]

        if present_years:
            roles = list(dict.fromkeys(h["role"] for h in source_history if h["found"] and h["role"]))
            timeline_parts.append(
                f"[{source_corp_name}] {min(present_years)}~{max(present_years)} 재직 "
                f"(직위: {', '.join(roles) if roles else '확인불가'})"
            )
        else:
            timeline_parts.append(f"[{source_corp_name}] 검색 기간 내 재직 이력 없음")

        if absent_years:
            timeline_parts.append(f"[{source_corp_name}] {min(absent_years)} 이후 임원 명단 미확인")

        if parent_company:
            group_count = len([a for a in affiliate_corp_list if a["source"] == "계열사"])
            chain_names = " → ".join(p["corp_name"] for p in parent_chain)
            timeline_parts.append(
                f"[그룹 탐색] 모회사 체인: {chain_names} / 계열사 {group_count}개 수집"
            )

        if found_at:
            seen_corp = set()
            for fa in found_at:
                key = fa["corp_name"]
                if key not in seen_corp:
                    seen_corp.add(key)
                    timeline_parts.append(
                        f"→ [{fa['corp_name']}] {fa['bsns_year']} 발견 "
                        f"(직위: {fa['role']}, 담당: {fa['chrg_job']}, 출처: {fa['source']})"
                    )
        else:
            timeline_parts.append(
                f"→ 검색한 {len(affiliate_corp_list)}개 관계사에서 '{params.name}'을(를) 찾지 못했습니다. "
                "미등기임원이라면 dart_search_disclosures로 공시 원문을 추가 검색하세요."
            )

        return json.dumps({
            "name": params.name,
            "source_company": {
                "corp_code": params.source_corp_code,
                "corp_name": source_corp_name,
                "history":   source_history,
            },
            "parent_company":           parent_company,
            "affiliates_searched_count": len(affiliate_corp_list),
            "affiliates_searched":       affiliate_corp_list,
            "found_at":                  found_at,
            "not_found_in":              not_found_affiliates,
            "timeline":                  "\n".join(timeline_parts),
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return _handle_error(e)


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    mcp.run()


if __name__ == "__main__":
    main()
