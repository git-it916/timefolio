import os, re, glob
import pandas as pd
from datetime import datetime

DB_DIR = "database"   # 입력 CSV 폴더
DB_DIR2 = "buy_list"  # 결과 저장 폴더
BASE_OUT = "buylist"  # 결과 파일 접두어
PATTERN = os.path.join(DB_DIR, "portfolio_*.csv")  # portfolio_YYYYMMDD_N.csv

_name_re = re.compile(r"portfolio_(\d{8})_(\d+)\.csv$", re.IGNORECASE)
_key_re = re.compile(r"^\d{8}_\d+$")  # 예: 20251023_2

def parse_info(path: str):
    m = _name_re.search(os.path.basename(path))
    if not m:
        return None
    return m.group(1), int(m.group(2))

def pick_latest_two_files():
    files = glob.glob(PATTERN)
    parsed = []
    for p in files:
        info = parse_info(p)
        if info:
            ymd, n = info
            parsed.append((ymd, n, p))
    if not parsed:
        raise RuntimeError("database 폴더에 portfolio_YYYYMMDD_N.csv 파일이 없습니다.")
    latest_ymd = max(x[0] for x in parsed)
    same_day = [(n, p) for y, n, p in parsed if y == latest_ymd]
    same_day.sort()
    if len(same_day) < 2:
        raise RuntimeError(f"{latest_ymd} 날짜의 CSV가 2개 미만입니다.")
    prev_path = same_day[-2][1]
    curr_path = same_day[-1][1]
    return latest_ymd, prev_path, curr_path

def _read_clean(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"rank": "Int64", "user_nick": str, "stock_name": str}, encoding="utf-8")
    for col in ["user_nick", "stock_name"]:
        df[col] = df[col].fillna("").astype(str).str.strip()
    df = df[(df["user_nick"] != "") & (df["stock_name"] != "")]
    df = df.drop_duplicates(subset=["user_nick", "stock_name"])
    return df

def next_out_path_for_date(out_dir: str, base: str, ymd: str) -> str:
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    m = 1
    while True:
        candidate = os.path.join(out_dir, f"{base}_{ymd}_{m}.csv")
        if not os.path.exists(candidate):
            return candidate
        m += 1

def compare_two_paths(curr_path: str, prev_path: str):
    # 현재/과거 파일명에서 현재 ymd를 뽑아 결과 파일명에 사용
    curr_info = parse_info(curr_path)
    if not curr_info:
        raise RuntimeError(f"현재 파일명 형식 오류: {curr_path}")
    curr_ymd, _ = curr_info

    print(f"[curr] {curr_path}")
    print(f"[prev] {prev_path}")

    prev_df = _read_clean(prev_path)
    curr_df = _read_clean(curr_path)

    prev_map = prev_df.groupby("user_nick")["stock_name"].apply(set).to_dict()
    curr_grp = curr_df.groupby("user_nick")

    rows = []
    for user, g in curr_grp:
        curr_set = set(g["stock_name"])
        prev_set = prev_map.get(user, set())
        new_stocks = sorted(curr_set - prev_set)
        try:
            rank_val = int(g["rank"].dropna().astype(int).min())
        except Exception:
            rank_val = None
        rows.append({
            "user_nick": user,
            "rank": rank_val,
            "new_count": len(new_stocks),
            "new_stocks": "; ".join(new_stocks)
        })

    out_df = pd.DataFrame(rows).sort_values(["new_count", "rank"], ascending=[False, True])
    out_path = next_out_path_for_date(DB_DIR2, BASE_OUT, curr_ymd)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ 저장 완료: {out_path}")
    return out_df

def compare_manual_or_auto(curr_key: str | None, prev_key: str | None):
    """
    curr_key/prev_key 예: '20251023_2'
    - 둘 다 주어지면 해당 두 파일을 사용
    - 비어있으면 자동으로 같은 날짜의 최근 2개 선택
    """
    if curr_key and prev_key:
        if not _key_re.match(curr_key):
            raise RuntimeError("현재 키 형식이 잘못되었습니다. 예: 20251023_2")
        if not _key_re.match(prev_key):
            raise RuntimeError("과거 키 형식이 잘못되었습니다. 예: 20251023_1")
        curr_path = os.path.join(DB_DIR, f"portfolio_{curr_key}.csv")
        prev_path = os.path.join(DB_DIR, f"portfolio_{prev_key}.csv")
        if not os.path.exists(curr_path):
            raise RuntimeError(f"파일이 없습니다: {curr_path}")
        if not os.path.exists(prev_path):
            raise RuntimeError(f"파일이 없습니다: {prev_path}")
        return compare_two_paths(curr_path, prev_path)
    else:
        # 자동 모드
        ymd, prev_path, curr_path = pick_latest_two_files()
        print(f"[auto] latest date = {ymd}")
        return compare_two_paths(curr_path, prev_path)

if __name__ == "__main__":
    try:
        # 인터랙티브 입력 (Enter만 치면 자동 모드)
        curr_key = input("현재 파일 키 (예: 20251023_2) [엔터=자동]: ").strip()
        prev_key = input("과거 파일 키 (예: 20251023_1) [엔터=자동]: ").strip()
        curr_key = curr_key or None
        prev_key = prev_key or None

        result = compare_manual_or_auto(curr_key, prev_key)
        print("\n=== Preview (top 10) ===")
        print(result.head(10).to_string(index=False))
    except Exception as e:
        print(f"에러: {e}")
