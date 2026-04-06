"""과거 스냅샷 백테스트."""

import pandas as pd

from timefolio.analyzer import analyze, list_snapshots


def main() -> None:
    snapshots = list_snapshots()
    print(f"총 {len(snapshots)}개 스냅샷, {len(snapshots)-1}개 비교쌍")
    print("=" * 80)

    all_results = []

    for i in range(1, len(snapshots)):
        prev_date, prev_seq, prev_path = snapshots[i - 1]
        curr_date, curr_seq, curr_path = snapshots[i]
        pair_label = f"{prev_date}_{prev_seq} -> {curr_date}_{curr_seq}"

        try:
            signals = analyze(curr_path, prev_path)

            strong_buys = [s for s in signals if s.signal == "STRONG_BUY"]
            buys = [s for s in signals if s.signal == "BUY"]
            holds = [s for s in signals if s.signal == "HOLD"]
            cautions = [s for s in signals if s.signal == "CAUTION"]

            new_entries = [s for s in signals if s.n_new_buyers > 0]
            droppers = [s for s in signals if s.n_droppers > 0]

            print(f"\n[{pair_label}]")
            print(
                f"  STRONG_BUY:{len(strong_buys)}  BUY:{len(buys)}"
                f"  HOLD:{len(holds)}  CAUTION:{len(cautions)}"
            )

            if strong_buys:
                names = ", ".join(
                    f"{s.stock_name}({s.score})" for s in strong_buys
                )
                print(f"  ** STRONG_BUY: {names}")
            if buys:
                names = ", ".join(
                    f"{s.stock_name}({s.score})" for s in buys[:5]
                )
                print(f"  ** BUY: {names}")

            if new_entries:
                top_entries = sorted(new_entries, key=lambda s: -s.n_new_buyers)[:3]
                names = ", ".join(
                    f"{s.stock_name}(+{s.n_new_buyers})" for s in top_entries
                )
                print(f"  >> 신규진입 TOP: {names}")

            if droppers:
                top_drops = sorted(droppers, key=lambda s: -s.n_droppers)[:3]
                names = ", ".join(
                    f"{s.stock_name}(-{s.n_droppers})" for s in top_drops
                )
                print(f"  << 이탈 TOP: {names}")

            all_results.append({
                "pair": pair_label,
                "STRONG_BUY": len(strong_buys),
                "BUY": len(buys),
                "HOLD": len(holds),
                "CAUTION": len(cautions),
                "신규진입종목": len(new_entries),
                "이탈종목": len(droppers),
                "총종목": len(signals),
            })

        except Exception as e:
            print(f"\n  ERROR {pair_label}: {e}")

    print("\n" + "=" * 80)
    print("  백테스트 요약")
    print("=" * 80)
    df = pd.DataFrame(all_results)
    print(df.to_string(index=False))

    # ── 시그널 추적: BUY 종목이 다음 스냅샷에서 어떻게 됐나? ──
    print("\n" + "=" * 80)
    print("  시그널 추적: BUY/STRONG_BUY -> 다음 스냅샷 결과")
    print("=" * 80)

    hit = 0
    miss = 0
    total_tracked = 0

    for i in range(1, len(snapshots) - 1):
        prev_path = snapshots[i - 1][2]
        curr_path = snapshots[i][2]
        next_path = snapshots[i + 1][2]

        curr_label = f"{snapshots[i][0]}_{snapshots[i][1]}"
        next_label = f"{snapshots[i + 1][0]}_{snapshots[i + 1][1]}"

        curr_signals = analyze(curr_path, prev_path)
        next_signals = analyze(next_path, curr_path)

        buy_stocks = {
            s.stock_name for s in curr_signals
            if s.signal in ("STRONG_BUY", "BUY")
        }
        if not buy_stocks:
            continue

        next_map = {s.stock_name: s for s in next_signals}

        print(f"\n  {curr_label} BUY -> {next_label}:")
        for stock in sorted(buy_stocks):
            ns = next_map.get(stock)
            total_tracked += 1
            if ns:
                still_good = ns.signal in ("STRONG_BUY", "BUY", "HOLD")
                marker = "OK" if still_good else "X"
                if still_good:
                    hit += 1
                else:
                    miss += 1
                delta = (
                    "+" + str(ns.momentum) if ns.momentum > 0
                    else str(ns.momentum)
                )
                print(
                    f"    [{marker}] {stock:12s} -> {ns.signal:12s}"
                    f"  점수:{ns.score:5.1f}  보유:{ns.n_holders}명  모멘텀:{delta}"
                )
            else:
                miss += 1
                print(f"    [X] {stock:12s} -> 완전 이탈")

    print("\n" + "=" * 80)
    if total_tracked > 0:
        rate = hit / total_tracked * 100
        print(
            f"  시그널 유지율: {hit}/{total_tracked} ({rate:.1f}%)"
            f"  - BUY 후 다음에도 BUY/HOLD 이상 유지"
        )
    else:
        print("  추적 가능한 BUY 시그널 없음")
    print("=" * 80)


if __name__ == "__main__":
    main()
