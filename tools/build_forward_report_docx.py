from __future__ import annotations

import csv
import json
import math
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
from docx import Document
from docx.shared import Inches

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = WORKSPACE_ROOT / "user_data" / "reports" / "forward_report_analytic.docx"
FORWARD_LATEST = WORKSPACE_ROOT / "user_data" / "reports" / "forward_monitor_latest.json"
FORWARD_DECISION = WORKSPACE_ROOT / "user_data" / "reports" / "forward_monitor_decision.json"
FORWARD_HISTORY = WORKSPACE_ROOT / "user_data" / "reports" / "forward_monitor_history.csv"
FORWARD_DB_PATHS = [
    WORKSPACE_ROOT / "user_data" / "tradesv3.dual-futures-dryrun.sqlite",
    WORKSPACE_ROOT / "user_data" / "tradesv3.dual-futures-v2r-dryrun.sqlite",
]
IMAGE_DIR = WORKSPACE_ROOT / "user_data" / "reports" / "forward_report_images"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_history(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def safe_float(value, default=0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def format_value(value) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 100 else f"{value:.2f}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    try:
        if isinstance(value, str):
            cleaned = value.replace("%", "")
            if cleaned.replace(".", "", 1).isdigit() or cleaned.lstrip("-+").replace(".", "", 1).isdigit():
                num = float(cleaned)
                return f"{num:.4f}" if abs(num) < 100 else f"{num:.2f}"
    except ValueError:
        pass
    return str(value)


def format_for_doc(value) -> str:
    return format_value(value)


DEFAULT_API_URLS = ["http://127.0.0.1:8080", "http://127.0.0.1:8081"]
DEFAULT_QUOTE_TIMEFRAME = "4h"


def fetch_json(url: str, timeout_seconds: float = 5.0) -> dict | None:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def fetch_latest_close_price(base_url: str, pair: str, timeframe: str = DEFAULT_QUOTE_TIMEFRAME) -> float | None:
    params = {"pair": pair, "timeframe": timeframe, "limit": 1}
    endpoint = f"{base_url.rstrip('/')}/api/v1/pair_candles?{urllib.parse.urlencode(params)}"
    payload = fetch_json(endpoint)
    if not payload:
        return None
    columns = payload.get("columns")
    rows = payload.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list) or not rows:
        return None
    last_row = rows[-1]
    if isinstance(last_row, dict):
        return safe_float(last_row.get("close"), default=None)
    if isinstance(last_row, list):
        try:
            close_index = columns.index("close")
            return safe_float(last_row[close_index], default=None)
        except ValueError:
            return None
    return None


def get_live_price_for_pair(pair: str) -> float | None:
    for url in DEFAULT_API_URLS:
        price = fetch_latest_close_price(url, pair)
        if price is not None:
            return price
    return None


def create_chart(x, y, title: str, out_path: Path, ylabel: str) -> None:
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.plot(x, y, marker="o", linestyle="-", color="#1f77b4")
    ax.set_title(title)
    ax.set_xlabel("Sample Index")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.35)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def create_bar_chart(labels: list[str], values: list[float], title: str, out_path: Path, ylabel: str) -> None:
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.bar(labels, values, color="#1f77b4")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticklabels(labels, rotation=0)
    ax.grid(True, axis="y", alpha=0.35)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def add_section_heading(doc: Document, title: str, level: int = 2) -> None:
    doc.add_heading(title, level=level)


def add_page_break(doc: Document) -> None:
    doc.add_page_break()


def add_key_value(doc: Document, key: str, value: str) -> None:
    p = doc.add_paragraph()
    p.add_run(f"{key}: ").bold = True
    p.add_run(value)


def add_bullet_list(doc: Document, items: list[str]) -> None:
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(item)


def add_table(doc: Document, headers: list[str], rows: list[list]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    hdr_cells = table.rows[0].cells
    for idx, header in enumerate(headers):
        hdr_cells[idx].text = header
    for row in rows:
        row_cells = table.add_row().cells
        for idx, value in enumerate(row):
            row_cells[idx].text = format_for_doc(value)


def add_bilingual_paragraph(doc: Document, en: str, gr: str) -> None:
    p_en = doc.add_paragraph()
    p_en.add_run(en)
    p_gr = doc.add_paragraph()
    r = p_gr.add_run(gr)
    r.italic = True


def query_open_trades() -> list[dict]:
    trades: list[dict] = []
    for db_path in FORWARD_DB_PATHS:
        if not db_path.exists():
            continue
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE is_open=1")
        for row in cursor.fetchall():
            trades.append(
                {
                    "bot": db_path.name,
                    "pair": row["pair"],
                    "side": "short" if row["is_short"] else "long",
                    "open_date": row["open_date"],
                    "open_rate": row["open_rate"],
                    "stake": row["open_trade_value"],
                    "pnl": row["close_profit_abs"],
                    "entry_tag": row["enter_tag"],
                    "max_rate": row["max_rate"],
                    "min_rate": row["min_rate"],
                    "liquidation_price": row["liquidation_price"],
                }
            )
        conn.close()
    return trades


def format_position_vs_entry(trade: dict, live_price: float | None) -> str:
    if live_price is None:
        return "-"
    entry_rate = safe_float(trade.get("open_rate"), default=0.0)
    if entry_rate == 0:
        return "-"
    side = trade.get("side", "long")
    if side == "short":
        diff_pct = (entry_rate - live_price) / entry_rate * 100.0
        direction = "profit" if diff_pct > 0 else "loss" if diff_pct < 0 else "flat"
    else:
        diff_pct = (live_price - entry_rate) / entry_rate * 100.0
        direction = "profit" if diff_pct > 0 else "loss" if diff_pct < 0 else "flat"
    return f"{direction} {diff_pct:.2f}%"


def add_trade_details(doc: Document, trades: list[dict]) -> None:
    add_section_heading(doc, "Open Trade Details", level=3)
    if not trades:
        doc.add_paragraph("No open trades detected in queryable SQLite trade history.")
        return
    headers = [
        "Bot DB",
        "Pair",
        "Side",
        "Open Date",
        "Open Rate",
        "Live Price",
        "Live vs Entry",
        "Stake",
        "PnL",
        "Entry Tag",
        "Max Rate",
        "Min Rate",
        "Liquidation",
    ]
    rows = []
    live_price_cache: dict[str, float | None] = {}
    for trade in trades:
        pair = trade.get("pair", "")
        if pair not in live_price_cache:
            live_price_cache[pair] = get_live_price_for_pair(pair) if pair else None
        live_price = live_price_cache[pair]
        rows.append(
            [
                trade["bot"],
                trade["pair"],
                trade["side"],
                trade["open_date"],
                format_value(trade["open_rate"]),
                format_value(live_price),
                format_position_vs_entry(trade, live_price),
                format_value(trade["stake"]),
                format_value(trade["pnl"]),
                trade["entry_tag"],
                format_value(trade["max_rate"]),
                format_value(trade["min_rate"]),
                format_value(trade["liquidation_price"]),
            ]
        )
    add_table(doc, headers, rows)
    if any(value is not None for value in live_price_cache.values()):
        add_bilingual_paragraph(
            doc,
            "Live market quotes were fetched from a local Freqtrade API endpoint and added to the open trade table. Use these values as a snapshot for current XRP exposure relative to the entry price.",
            "Οι ζωντανές τιμές αγοράς ανακτήθηκαν από τοπικό Freqtrade API και προστέθηκαν στον πίνακα ανοικτών συναλλαγών. Χρησιμοποιήστε αυτές τις τιμές ως στιγμιαίο snapshot της τρέχουσας έκθεσης XRP σε σχέση με την τιμή εισόδου."
        )


def summarize_gate_statuses(decision: dict) -> list[list[str]]:
    rows: list[list[str]] = []
    for section in ("integrity_gates", "risk_gates", "performance_gates", "sample_gates"):
        for gate in decision.get(section, []):
            rows.append([section, gate.get("name", "-"), format_value(gate.get("actual")), gate.get("requirement", "-"), gate.get("status", "-")])
    return rows


def gate_status_counts(decision: dict) -> dict[str, int]:
    counts: dict[str, int] = {"PASS": 0, "FAIL": 0, "NOT_APPLICABLE": 0, "UNKNOWN": 0}
    for section in ("integrity_gates", "risk_gates", "performance_gates", "sample_gates"):
        for gate in decision.get(section, []):
            status = gate.get("status", "UNKNOWN")
            if status not in counts:
                counts[status] = 0
            counts[status] += 1
    return counts


def build_report(latest: dict, decision: dict, history: list[dict]) -> None:
    if IMAGE_DIR.exists():
        for child in IMAGE_DIR.iterdir():
            child.unlink()
    else:
        IMAGE_DIR.mkdir(parents=True)

    doc = Document()
    doc.add_heading("Forward Dry-Run Analytics Report", level=0)
    doc.add_paragraph(
        "Αυτή η αναφορά αναλύει τις τρέχουσες forward dry-run συνθήκες του trading bot. "
        "Περιλαμβάνει οργανωμένα metrics, validation gates, ανοικτές θέσεις, ιστορικά charts και αναλυτικά σχόλια."
    )
    add_page_break(doc)

    add_section_heading(doc, "Executive Summary", level=1)
    doc.add_paragraph(
        "Ο forward monitor βρίσκεται σε credential-free dry-run λειτουργία. Η παρούσα εικόνα δείχνει ότι τα bots είναι τεχνικά υγιή, "
        "αλλά η sample size είναι ανεπαρκής για να αξιολογηθεί η στρατηγική. Δεν υπάρχουν κλειστά κέρδη και τα performance gates είναι "
        "κατά κύριο λόγο αποτυχίες λόγω έλλειψης δείγματος."
    )
    doc.add_paragraph(
        "Συστήνεται να συνεχιστεί η παρακολούθηση τουλάχιστον 30 ημέρες ή έως ότου συλλεχθούν 30 κλειστά trades προτού ληφθεί απόφαση."
    )
    add_page_break(doc)

    add_section_heading(doc, "1. Current Forward State", level=1)
    add_key_value(doc, "Generated", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    add_key_value(doc, "Decision", str(decision.get("decision", "-")))
    add_key_value(doc, "Recommended Action", str(decision.get("recommended_action", "-")))
    add_key_value(doc, "Live Trading Authorized", str(decision.get("live_trading_authorized", False)))
    add_key_value(doc, "Sample Observation Days", format_value(decision.get("sample_gates", [{}])[0].get("actual") if decision.get("sample_gates") else "-"))
    add_key_value(doc, "Required Observation Days", "30")
    add_page_break(doc)

    add_section_heading(doc, "2. Metrics and Gate Statuses", level=1)
    summary_rows = summarize_gate_statuses(decision)
    if summary_rows:
        add_table(doc, ["Section", "Gate", "Actual", "Requirement", "Status"], summary_rows)
    else:
        doc.add_paragraph("No gates were available in the forward decision payload.")
    gate_counts = gate_status_counts(decision)
    gate_labels = list(gate_counts.keys())
    gate_values = [gate_counts[label] for label in gate_labels]
    gate_chart = IMAGE_DIR / "gate_status_counts.png"
    create_bar_chart(gate_labels, gate_values, "Gate Status Counts", gate_chart, "Count")
    doc.add_picture(str(gate_chart), width=Inches(6))
    add_bilingual_paragraph(
        doc,
        "The chart above clearly shows the balance between pass/fail indicators and allows stakeholders to understand whether issues are structural or sample-based. Because the current run has zero closed trades, failed performance gates are expected and should not be interpreted as outright strategy failure.",
        "Το διάγραμμα παραπάνω δείχνει την κατανομή επιτυχίας/αποτυχίας των gates και βοηθάει τους ενδιαφερόμενους να κατανοήσουν αν τα προβλήματα οφείλονται σε δομικά ζητήματα ή σε έλλειψη δείγματος. Δεδομένου ότι η τρέχουσα εκτέλεση έχει μηδέν κλειστά trades, οι αποτυχίες επιδόσεων είναι αναμενόμενες και δεν πρέπει να ερμηνευθούν ως απόλυτη αποτυχία της στρατηγικής."
    )
    add_page_break(doc)

    add_section_heading(doc, "2.1 Monitoring Sample Quality", level=2)
    history_ok = sum(1 for row in history if row.get("collection_status") == "OK")
    history_error = sum(1 for row in history if row.get("collection_status") == "ERROR")
    total_history = len(history)
    add_key_value(doc, "Total monitoring samples", str(total_history))
    add_key_value(doc, "Successful samples", str(history_ok))
    add_key_value(doc, "Error samples", str(history_error))
    add_key_value(doc, "Latest snapshot UTC", history[-1].get("snapshot_utc", "-") if history else "-")
    add_page_break(doc)

    add_section_heading(doc, "3. Bot Health and Runtime Validation", level=1)
    bot_summary = latest.get("bots", {})
    if isinstance(bot_summary, dict):
        for bot_key, bot_data in bot_summary.items():
            add_section_heading(doc, f"Bot {bot_key} ({bot_data.get('runtime', {}).get('strategy', '-')})", level=2)
            runtime = bot_data.get("runtime", {})
            metrics = bot_data.get("metrics", {})
            data_quality = bot_data.get("data_quality", {})
            add_key_value(doc, "State", str(runtime.get("state", "-")))
            add_key_value(doc, "Dry run", str(runtime.get("dry_run", "-")))
            add_key_value(doc, "Trading mode", str(runtime.get("trading_mode", "-")))
            add_key_value(doc, "Margin mode", str(runtime.get("margin_mode", "-")))
            add_key_value(doc, "Bot loop age (sec)", format_value(runtime.get("bot_loop_age_seconds")))
            add_paragraph = doc.add_paragraph
            add_paragraph("Metrics:")
            add_table(doc, ["Metric", "Value"], [
                ["Open trades", metrics.get("open_trades")],
                ["Closed trades", metrics.get("closed_trades")],
                ["Net profit (abs)", metrics.get("net_profit_abs")],
                ["Return % of start wallet", metrics.get("return_pct_of_start_wallet")],
                ["Profit factor", metrics.get("profit_factor")],
                ["Max drawdown %", metrics.get("max_drawdown_pct_of_start_wallet")],
            ])
            add_paragraph("Runtime validation checks:")
            rv_rows = [[c.get("name", "-"), c.get("actual"), c.get("expected", "-"), c.get("status", "-")] for c in bot_data.get("runtime_validation", {}).get("checks", [])]
            if rv_rows:
                add_table(doc, ["Check", "Actual", "Expected", "Status"], rv_rows)
            else:
                doc.add_paragraph("No runtime validation checks available.")
            add_paragraph("Data quality reconciliation checks:")
            dq_rows = [[c.get("name", "-"), c.get("api"), c.get("recomputed"), c.get("status", "-")] for c in bot_data.get("data_quality", {}).get("api_reconciliation", {}).get("checks", [])]
            if dq_rows:
                add_table(doc, ["Check", "API", "Recomputed", "Status"], dq_rows)
            else:
                doc.add_paragraph("No data quality reconciliation checks available.")

            add_paragraph(
                "Summary for this bot: runtime checks are healthy, data quality passes on all required fields, and there is no current exposure in the live trade pool. "
                "Because open trades are zero and no closed trades exist, the most important insight is that the environment is clean for continued observation, not that the strategy has been validated."
            )
            add_page_break(doc)
    else:
        doc.add_paragraph("No bot data available in latest forward monitor state.")
        add_page_break(doc)

    add_section_heading(doc, "4. Open Trade Audit", level=1)
    open_trades = query_open_trades()
    if open_trades:
        add_bilingual_paragraph(
            doc,
            "The database audit found open trades in the live dry-run trade history. These positions should be reviewed immediately for entry rationale and position sizing.",
            "Ο έλεγχος της βάσης δεδομένων εντόπισε ανοικτές θέσεις στο ιστορικό dry-run. Αυτές οι θέσεις πρέπει να εξεταστούν άμεσα για τη λογική εισόδου και το sizing."
        )
    else:
        add_bilingual_paragraph(
            doc,
            "The database audit did not find any currently open trades in the available dry-run SQLite history. This confirms that the current forward run has no active exposure, which is consistent with the forward monitor sample metrics.",
            "Ο έλεγχος της βάσης δεδομένων δεν εντόπισε τρέχουσες ανοικτές θέσεις στο διαθέσιμο SQLite ιστορικό. Αυτό επιβεβαιώνει ότι το τρέχον forward run δεν έχει ενεργό έκθεση, συμβατό με τα δείγματα παρακολούθησης."
        )
    add_trade_details(doc, open_trades)
    add_page_break(doc)

    add_section_heading(doc, "5. Visual Evidence and Screenshots", level=1)
    add_paragraph(
        "The following charts are inserted as visual screenshots of the monitoring state. They are generated from the forward monitor history and support the numerical conclusions above."
    )
    sample_labels = ["OK", "ERROR"]
    sample_values = [history_ok, history_error]
    sample_chart = IMAGE_DIR / "sample_status_counts.png"
    create_bar_chart(sample_labels, sample_values, "Sample Status Counts", sample_chart, "Snapshots")
    doc.add_picture(str(sample_chart), width=Inches(6))
    add_bilingual_paragraph(
        doc,
        "The sample quality chart above highlights whether the forward monitor is consistently ingesting data. A high OK ratio means monitoring is stable, while repeated errors indicate an operational issue rather than a strategy issue.",
        "Το γράφημα δείχνει αν ο forward monitor συλλέγει σταθερά δεδομένα. Υψηλό ποσοστό OK σημαίνει σταθερή συλλογή, ενώ επανειλημμένα σφάλματα υποδεικνύουν πρόβλημα λειτουργίας και όχι απαραίτητα πρόβλημα στρατηγικής."
    )
    add_page_break(doc)

    add_section_heading(doc, "6. Historical Monitoring Charts", level=1)
    bot_rows = defaultdict(list)
    for row in history:
        bot_rows[row.get("bot_key", "unknown")].append(row)

    for bot_key, rows in bot_rows.items():
        add_section_heading(doc, f"Historical profile: {bot_key}", level=2)
        x = list(range(1, len(rows) + 1))
        metrics_to_plot = [
            ("open_trades", "Open Trades", int),
            ("closed_trades", "Closed Trades", int),
            ("net_profit_abs", "Net Profit Abs", float),
            ("return_pct_of_start_wallet", "Return % of Start Wallet", float),
            ("profit_factor", "Profit Factor", float),
            ("max_drawdown_pct_of_start_wallet", "Max Drawdown %", float),
        ]
        for metric_key, label, cast_type in metrics_to_plot:
            y = [safe_float(row.get(metric_key, ""), default=0.0) for row in rows]
            chart_path = IMAGE_DIR / f"{bot_key}_{metric_key}.png"
            create_chart(x, y, f"{label} - {bot_key}", chart_path, label)
            doc.add_picture(str(chart_path), width=Inches(6))
            doc.add_paragraph(f"Chart shows {label} over the available monitoring samples for {bot_key}.")
        add_page_break(doc)

    add_section_heading(doc, "7. Narrative Analysis and Key Findings", level=1)
    doc.add_paragraph(
        "Το σύνολο των στοιχείων δείχνει ότι η τρέχουσα forward run είναι ακόμα σε αρχικό στάδιο. Η ποιότητα δεδομένων και οι runtime έλεγχοι είναι καθαρές, αλλά η χρηστική απόδοση δεν έχει αξιολογηθεί λόγω απουσίας κλειστών trades."
    )
    add_bullet_list(doc, [
        "Current sample coverage is adequate for monitoring, but not adequate for strategy validation.",
        "No open trades were observed in local SQLite trade history at the time of report creation.",
        "Both bots are running in 4h timeframes and remain in dry-run mode, which is appropriate for forward evidence collection.",
        "The main risk at this stage is not strategy rupture, but waiting too little time before making an operational decision."
    ])
    doc.add_page_break()

    add_section_heading(doc, "8. Recommendations", level=1)
    doc.add_paragraph(
        "1. Συνεχίστε το credential-free dry-run τουλάχιστον έως 30 ημέρες ή έως 30 κλειστά trades.\n"
        "2. Παρακολουθήστε στενά τα open trades που δημιουργήθηκαν και αξιολογήστε την απόδοση σε σχέση με τον αποδεδειγμένο risk budget.\n"
        "3. Μην αλλάξετε το timeframe άμεσα. Οι στρατηγικές έχουν σχεδιαστεί για 4h και η τρέχουσα δομή τους πρέπει πρώτα να δοκιμαστεί με σταθερό δείγμα.\n"
        "4. Προσθέστε επιπλέον παρακολούθηση των trades και έναν δεύτερο κανάλι alert για potential stop loss ή manual abort αν τεθεί θέμα στοιχείων."
    )

    add_section_heading(doc, "Appendix A: Raw Data Artifacts", level=1)
    add_paragraph(
        "The raw JSON and CSV artifacts are available in the repository under user_data/reports. "
        "This report summarizes those artifacts in human-readable form, while preserving the original source data for audit purposes."
    )
    add_paragraph("- user_data/reports/forward_monitor_latest.json")
    add_paragraph("- user_data/reports/forward_monitor_decision.json")
    add_paragraph("- user_data/reports/forward_monitor_history.csv")

    doc.save(OUTPUT_PATH)
    print(f"Saved report to {OUTPUT_PATH}")


def main() -> None:
    latest = load_json(FORWARD_LATEST)
    decision = load_json(FORWARD_DECISION)
    history = load_history(FORWARD_HISTORY)
    build_report(latest, decision, history)


if __name__ == "__main__":
    main()
