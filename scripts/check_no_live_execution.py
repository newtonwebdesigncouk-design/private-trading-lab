"""Fail CI if runtime code gains external execution-shaped capabilities."""

import ast
from pathlib import Path

from app.models.enums import StrategyState, TradingMode

FORBIDDEN_CALLABLES = {
    "submit_live_order",
    "place_live_order",
    "transmit_order",
    "send_order_to_broker",
    "enable_live_trading",
}
FORBIDDEN_SETTINGS = {
    "broker_api_key",
    "broker_secret",
    "exchange_api_key",
    "exchange_secret",
}
FORBIDDEN_RUNTIME_IMPORTS = {"requests", "aiohttp", "websockets", "ccxt", "ib_insync"}


def scan(root: Path = Path("app")) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.lower() in FORBIDDEN_CALLABLES
            ):
                findings.append(f"{path}:{node.lineno}: forbidden callable {node.name}")
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id.lower() in FORBIDDEN_SETTINGS
            ):
                findings.append(f"{path}:{node.lineno}: forbidden credential setting")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in FORBIDDEN_RUNTIME_IMPORTS:
                        findings.append(f"{path}:{node.lineno}: forbidden runtime network client")
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[0] in FORBIDDEN_RUNTIME_IMPORTS
            ):
                findings.append(f"{path}:{node.lineno}: forbidden runtime network client")
    if {mode.value for mode in TradingMode} != {"BACKTEST", "PAPER"}:
        findings.append("TradingMode contains a mode outside BACKTEST/PAPER")
    if "LIVE" in {state.value for state in StrategyState}:
        findings.append("StrategyState contains forbidden LIVE state")
    return findings


def main() -> None:
    findings = scan()
    if findings:
        raise SystemExit("Unsafe execution surface detected:\n" + "\n".join(findings))
    print("Safety scan passed: simulation-only modes and no external execution surface detected.")


if __name__ == "__main__":
    main()
