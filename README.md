# DART MCP Server

대한민국 전자공시시스템(DART) OpenAPI를 Claude에서 직접 사용할 수 있게 해주는 MCP(Model Context Protocol) 서버입니다.

DART에 공시된 기업 정보, 재무제표, 임원 현황, 주주 정보 등 **59개 도구**를 제공합니다.

## 주요 기능

- **공시 검색**: 날짜/기업/유형별 공시보고서 검색
- **정기보고서**: 사업보고서, 분기·반기보고서의 주요 재무·경영 정보
- **재무정보**: 재무상태표, 손익계산서, XBRL 데이터
- **지분공시**: 대량보유·임원 주식 변동 현황
- **주요사항보고서**: 유상증자, M&A, 전환사채 등 주요 이벤트
- **증권신고서**: 주식·채권·합병 신고서 정보
- **임원 이동 추적**: 특정 임원이 그룹 내 어느 계열사로 이동했는지 자동 탐색

## 설치 및 설정

### 사전 요구사항

- Python 3.10 이상
- [DART OpenAPI 키](https://opendart.fss.or.kr) (무료 발급)
- Claude Desktop

### 설치

```bash
git clone https://github.com/bigbear0102/dart-mcp.git
cd dart-mcp
python -m venv .venv

# Windows
.venv\Scripts\pip install -e .

# macOS/Linux
.venv/bin/pip install -e .
```

### Claude Desktop 설정

`%APPDATA%\Claude\claude_desktop_config.json` (Windows) 또는  
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)에 아래 내용을 추가합니다.

```json
{
  "mcpServers": {
    "dart": {
      "command": "C:\\Users\\YOUR_USERNAME\\dart-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\YOUR_USERNAME\\dart-mcp\\server.py"],
      "env": {
        "DART_API_KEY": "여기에_발급받은_API_키_입력"
      }
    }
  }
}
```

`YOUR_USERNAME`과 API 키를 실제 값으로 교체한 뒤 Claude Desktop을 재시작합니다.

## 사용 예시

Claude에서 아래와 같이 질문할 수 있습니다.

```
삼성전자의 corp_code를 찾아줘
→ dart_find_company_by_name (keyword: "삼성전자")

삼성전자(00126380)의 2023년 사업보고서 임원 현황을 알려줘
→ dart_get_executives

SK하이닉스에서 퇴임한 홍길동이 어느 계열사로 이동했는지 추적해줘
→ dart_track_executive_movement

삼성전자의 2023년 연결 재무제표를 보여줘
→ dart_get_single_company_full_financials
```

## 도구 목록

### DS001 - 공시정보 (4개)

| 도구명 | 설명 |
|---|---|
| `dart_search_disclosures` | 공시보고서 검색 (날짜/기업/유형별) |
| `dart_get_company_info` | 기업 개황 조회 |
| `dart_get_company_codes` | DART 전체 기업 고유번호 목록 다운로드 |
| `dart_get_document` | 공시서류 원본 파일 다운로드 |

### DS002 - 정기보고서 주요정보 (28개)

증자현황, 배당, 자기주식, 최대주주, 임원, 직원, 보수, 타법인출자현황 등 사업보고서 핵심 데이터.

| 도구명 | 설명 |
|---|---|
| `dart_get_capital_changes` | 증자(감자) 현황 |
| `dart_get_dividend_info` | 배당 현황 |
| `dart_get_treasury_stock_status` | 자기주식 현황 |
| `dart_get_major_shareholders` | 최대주주 현황 |
| `dart_get_major_shareholder_changes` | 최대주주 변동 현황 |
| `dart_get_minority_shareholders` | 소액주주 현황 |
| `dart_get_executives` | 임원 현황 |
| `dart_get_employees` | 직원 현황 |
| `dart_get_individual_compensation_5b` | 개인별 보수 현황 (5억 이상) |
| `dart_get_total_executive_compensation` | 임원 전체 보수 현황 |
| `dart_get_top5_compensation` | 상위 5인 보수 현황 |
| `dart_get_investments_in_other_corps` | 타법인 출자 현황 |
| `dart_get_total_shares` | 전체 주식 현황 |
| `dart_get_debt_securities_issuance` | 채무증권 발행 현황 |
| `dart_get_cp_balance` | 기업어음(CP) 잔액 현황 |
| `dart_get_short_term_bond_balance` | 단기사채 잔액 현황 |
| `dart_get_corporate_bond_balance` | 회사채 잔액 현황 |
| `dart_get_hybrid_securities_balance` | 신종자본증권 잔액 현황 |
| `dart_get_contingent_capital_balance` | 조건부자본증권 잔액 현황 |
| `dart_get_audit_opinion` | 감사의견 |
| `dart_get_audit_service_contract` | 감사용역 계약 현황 |
| `dart_get_non_audit_service_contract` | 비감사용역 계약 현황 |
| `dart_get_outside_directors` | 사외이사 현황 |
| `dart_get_unregistered_exec_compensation` | 미등기임원 보수 현황 |
| `dart_get_compensation_shareholder_approval` | 이사·감사 전체 보수 현황 |
| `dart_get_compensation_by_type` | 보수 지급 유형별 현황 |
| `dart_get_public_offering_fund_usage` | 공모자금 사용 현황 |
| `dart_get_private_placement_fund_usage` | 사모자금 사용 현황 |

### DS003 - 재무정보 (7개)

| 도구명 | 설명 |
|---|---|
| `dart_get_single_company_accounts` | 단일 기업 주요 계정 조회 |
| `dart_get_multi_company_accounts` | 복수 기업 주요 계정 비교 |
| `dart_get_single_company_full_financials` | 단일 기업 전체 재무제표 |
| `dart_get_xbrl_files` | XBRL 재무제표 파일 목록 |
| `dart_get_xbrl_taxonomy` | XBRL 재무제표 데이터 |
| `dart_get_single_company_financial_index` | 단일 기업 재무 지표 |
| `dart_get_multi_company_financial_index` | 복수 기업 재무 지표 비교 |

### DS004 - 지분공시 (2개)

| 도구명 | 설명 |
|---|---|
| `dart_get_large_shareholder_report` | 대량보유 상황 보고 |
| `dart_get_officer_shareholder_report` | 임원·주요주주 소유 보고 |

### DS005 - 주요사항보고서 (36개)

유상증자, 무상증자, 감자, 합병, 분할, 전환사채, 신주인수권부사채, 자기주식 취득/처분, 소송, 부도, 영업정지 등 주요 이벤트 보고서.

### DS006 - 증권신고서 (6개)

| 도구명 | 설명 |
|---|---|
| `dart_get_equity_securities_registration` | 지분증권 신고서 |
| `dart_get_debt_securities_registration` | 채무증권 신고서 |
| `dart_get_depositary_receipts_registration` | 증권예탁증권 신고서 |
| `dart_get_merger_registration` | 합병 신고서 |
| `dart_get_comprehensive_stock_exchange_registration` | 주식의포괄적교환·이전 신고서 |
| `dart_get_division_registration` | 분할 신고서 |

### 임원 이동 추적 (3개)

| 도구명 | 설명 |
|---|---|
| `dart_find_company_by_name` | 회사명 키워드로 corp_code 검색 (11만여 개 전체 탐색) |
| `dart_search_executive_by_name` | 여러 기업에서 특정 이름의 임원 검색 |
| `dart_track_executive_movement` | 임원의 그룹 계열사 간 이동 경로 자동 추적 |

#### 임원 이동 추적 동작 방식

`dart_track_executive_movement`는 다음 순서로 자동 탐색합니다.

1. 원래 기업에서 임원 재직 이력 조회
2. 최대주주 현황에서 모회사 탐색
3. 모회사의 타법인출자현황으로 형제 계열사 수집 (최대 3단계 재귀)
4. 원래 기업의 자회사 수집
5. `affiliate_keywords` 제공 시 키워드 매칭 기업 추가
6. 수집된 계열사 전체에서 임원 검색 후 이동 경로 반환

> **주의**: DART exctvSttus API는 등기임원(이사회 구성원)만 조회됩니다.  
> 미등기임원(부사장, 전무, 상무 등)은 `dart_search_disclosures`로 공시 원문을 추가 검색하세요.

## API 키 발급

1. [DART 오픈API](https://opendart.fss.or.kr) 접속
2. 회원가입 후 API 키 신청
3. 승인 후 발급된 키를 `DART_API_KEY` 환경변수에 설정

## 라이선스

MIT
