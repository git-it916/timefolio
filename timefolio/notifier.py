"""
텔레그램 봇 알림 모듈.

분석 결과를 텔레그램 메시지로 전송한다.
"""

import logging
import os
from datetime import datetime

# conda 환경의 SSL_CERT_FILE 경로 문제 수정
if os.environ.get("SSL_CERT_FILE") and not os.path.exists(os.environ["SSL_CERT_FILE"]):
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()

import telegram

from timefolio.analyzer import StockSignal, UserTrade
from timefolio.config import (
    RANKS_TO_SCRAPE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TOP_TIER,
)

log = logging.getLogger(__name__)


def _format_signal_message(signals: list[StockSignal]) -> str:
    """시그널 리스트를 텔레그램 메시지 문자열로 변환."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        f"📊 *Timefolio 시그널 리포트*",
        f"🕐 {now} | 상위 {RANKS_TO_SCRAPE}명 분석",
        "",
    ]

    groups: dict[str, list[StockSignal]] = {}
    for s in signals:
        groups.setdefault(s.signal, []).append(s)

    emoji_map = {
        "STRONG_BUY": "🔴 STRONG BUY",
        "BUY": "🟠 BUY",
        "HOLD": "🟡 HOLD",
        "CAUTION": "🔵 CAUTION",
        "NEUTRAL": "⚪ NEUTRAL",
    }

    # STRONG_BUY, BUY, HOLD, CAUTION만 표시 (NEUTRAL은 종목이 너무 많으므로 개수만)
    for sig_type in ["STRONG_BUY", "BUY", "HOLD", "CAUTION"]:
        items = groups.get(sig_type, [])
        if not items:
            continue

        lines.append(f"*{emoji_map[sig_type]}* ({len(items)}종목)")
        for s in items:
            momentum_icon = "↑" if s.momentum > 0 else ("↓" if s.momentum < 0 else "→")
            lines.append(
                f"  `{s.stock_name:10s}` "
                f"점수:{s.score:5.1f} "
                f"보유:{s.n_holders}명 "
                f"T{TOP_TIER}:{s.top_tier_holders} "
                f"{momentum_icon}{abs(s.momentum)}"
            )
        lines.append("")

    neutral_count = len(groups.get("NEUTRAL", []))
    if neutral_count:
        lines.append(f"*{emoji_map['NEUTRAL']}* {neutral_count}종목")
        lines.append("")

    # 컨센서스 Top 10
    top10 = sorted(signals, key=lambda s: -s.n_holders)[:10]
    lines.append("*📈 컨센서스 Top 10*")
    for i, s in enumerate(top10, 1):
        pct = s.n_holders / RANKS_TO_SCRAPE * 100
        lines.append(f"  {i}. {s.stock_name} -- {s.n_holders}명({pct:.0f}%)")

    return "\n".join(lines)


def _format_trades_message(trades: list[UserTrade]) -> str:
    """TOP20 유저 매매 내역을 텔레그램 메시지로 변환."""
    if not trades:
        return ""

    lines: list[str] = [
        "",
        "*👤 TOP20 유저 매매 내역*",
        "",
    ]
    for t in trades:
        parts: list[str] = []
        if t.bought:
            parts.append(f"+{', '.join(t.bought)}")
        if t.sold:
            parts.append(f"-{', '.join(t.sold)}")
        lines.append(f"  `{t.rank:2d}위` {t.user_nick}: {' / '.join(parts)}")

    return "\n".join(lines)


def _format_scrape_only_message(csv_path: str) -> str:
    """스크래핑만 완료된 경우의 메시지."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"📥 *스크래핑 완료*\n"
        f"🕐 {now}\n"
        f"스냅샷이 1개뿐이어서 비교 분석은 다음 실행 시 진행됩니다."
    )


def _format_error_message(error: Exception) -> str:
    """에러 발생 시 메시지."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"❌ *실행 오류*\n"
        f"🕐 {now}\n"
        f"`{type(error).__name__}: {error}`"
    )


async def _send_telegram(text: str) -> None:
    """텔레그램 메시지 전송 (비동기)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("텔레그램 설정 누락 (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return

    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=text,
        parse_mode=telegram.constants.ParseMode.MARKDOWN,
    )
    log.info("텔레그램 메시지 전송 완료")


def send_signal_report(
    signals: list[StockSignal],
    trades: list[UserTrade] | None = None,
) -> None:
    """분석 결과를 텔레그램으로 전송 (동기 래퍼)."""
    import asyncio

    text = _format_signal_message(signals)
    if trades:
        text += _format_trades_message(trades)
    asyncio.run(_send_telegram(text))


def send_scrape_only(csv_path: str) -> None:
    """스크래핑만 완료 알림."""
    import asyncio

    text = _format_scrape_only_message(csv_path)
    asyncio.run(_send_telegram(text))


def send_error(error: Exception) -> None:
    """에러 알림."""
    import asyncio

    text = _format_error_message(error)
    asyncio.run(_send_telegram(text))
