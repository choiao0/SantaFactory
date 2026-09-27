# 3. DB 덤프 (최신본)

운영 DB(EC2 컨테이너 `a106-db`, PostgreSQL 16.15)를 2026-09-27 23:21 KST 에 뜬 덤프다. release `46e2c38`(Jenkins #34) 기준, Flyway V1~V14 + `R__seed_demo` 적용 상태.

## 파일

| 파일 | 형식 | 크기 | md5 | 내용 |
|---|---|---:|---|---|
| `santafactory_20260927.sql` | 평문 SQL | 18,071,209 B (17 MB) | `aa9995c1a5f9ef5b4edde94768078c5b` | 스키마 + 데이터. 단 `simscenario_replays` 는 **구조만**(데이터 제외) |
| `santafactory_20260927_full.dump` | `pg_dump -Fc` (압축 9) | 58,703,046 B (56 MB) | `063ffc53b72bcfdf2330408c924d4d76` | 스키마 + **전체** 데이터 |

`simscenario_replays` 는 견적 DES 의 로봇 궤적(검증 영상 재생용)으로 DB 402 MB 가운데 375 MB 를 차지한다. 스키마와 업무 데이터를 읽기만 할 때는 SQL 판, 검증 재생까지 그대로 되살릴 때는 전체 판을 쓴다.

## 만든 방법

```bash
# SQL 판 — 소유자·권한 문장 없이, 궤적 테이블 데이터만 빼고
docker exec a106-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges \
    --exclude-table-data=simscenario_replays' > santafactory_20260927.sql
# 전체 판 — custom 형식, 최대 압축 (소유자 정보는 복원 때 --no-owner 로 무시)
docker exec a106-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z 9' > santafactory_20260927_full.dump
docker exec -i a106-db pg_restore -f /dev/null < santafactory_20260927_full.dump    # 끝까지 읽히는지 확인
```

## 들어 있는 것 (복원 뒤 행 수)

| 테이블 | SQL 판 | 전체 판 |
|---|---:|---:|
| `estimates` (견적) | 6 | 6 |
| `members` (회원: 관리자 · 데모) | 2 | 2 |
| `simscenarios` (DES 런) | 70 | 70 |
| `simscenario_replays` (DES 궤적) | 0 | 70 |
| `simscenario_verify_slices` (3D 검증 구간) | 48 | 48 |
| `flyway_schema_history` | V1~V14 + R | V1~V14 + R |

표에 없는 나머지 테이블(`warehouses` · `zones` · `rack` · `facility` · `stores` · `products` · `orders` · `inbounds` · `outbounds` · `tasks` · `robots` · `workers` · `estimate_verifications`)도 스키마와 데이터가 모두 들어 있다(전체 19개).
회원 비밀번호는 BCrypt 해시로만 들어 있다. 검증 영상 파일은 DB 가 아니라 MinIO(`verify-videos` 버킷)에 있고, DB 에는 객체 키만 있다.

## 복원

빈 PostgreSQL 16 에 되살린다(검증: `postgres:16-alpine` 컨테이너에서 두 파일 모두 복원해 위 행 수 확인).

```bash
# 빈 DB 준비
docker run -d --name santa-restore -e POSTGRES_USER=santa -e POSTGRES_PASSWORD=<임의> -e POSTGRES_DB=santafactory postgres:16-alpine

# SQL 판
docker exec -i santa-restore psql -U santa -d santafactory -v ON_ERROR_STOP=1 < santafactory_20260927.sql

# 또는 전체 판
docker exec -i santa-restore pg_restore -U santa -d santafactory --no-owner --no-privileges < santafactory_20260927_full.dump
```

- SQL 판 첫머리에 `\restrict` 줄이 있어 **psql 16.10 이상**(또는 17.6 이상)이 필요하다. 오래된 psql 이면 그 줄과 끝의 `\unrestrict` 줄을 지우고 넣는다.
- 되살린 DB 에 백엔드를 붙이면 Flyway 가 이력(`flyway_schema_history`)을 보고 추가 마이그레이션만 적용한다 — **이 테이블은 지우지 않는다.**
- 운영 DB 를 이 덤프로 덮어쓸 때는 먼저 현재 DB 를 덤프해 둔다(Jenkins 도 백엔드 배포 전 `/var/lib/jenkins/db-backup` 에 자동으로 뜬다).
