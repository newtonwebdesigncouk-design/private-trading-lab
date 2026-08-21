"""Fail CI if runtime code gains execution, funding, or unapproved network capability."""

import ast
from pathlib import Path

from app.models.enums import StrategyState, TradingMode

FORBIDDEN_CALLABLES = {
    "submit_live_order",
    "place_live_order",
    "place_external_order",
    "transmit_order",
    "send_order_to_broker",
    "enable_live_trading",
    "deposit_funds",
    "withdraw_funds",
    "transfer_funds",
}
FORBIDDEN_SETTINGS = {
    "broker_api_key",
    "broker_secret",
    "broker_password",
    "exchange_api_key",
    "exchange_secret",
    "exchange_password",
}
NETWORK_IMPORTS = {"requests", "httpx", "aiohttp", "urllib", "http", "socket", "websockets"}
FORBIDDEN_SDK_IMPORTS = {"ccxt", "ib_insync", "alpaca", "binance", "coinbase"}
WRITE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def scan(root: Path = Path("app")) -> list[str]:
    findings: list[str] = []
    approved_network_root = root / "data" / "providers"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        network_allowed = _inside(path, approved_network_root)
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
                findings.append(f"{path}:{node.lineno}: forbidden trading credential setting")
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module.split(".")[0]]
            for module in imported:
                if module in FORBIDDEN_SDK_IMPORTS:
                    findings.append(
                        f"{path}:{getattr(node, 'lineno', 0)}: forbidden trading SDK import "
                        f"{module}"
                    )
                if module in NETWORK_IMPORTS and not network_allowed:
                    findings.append(
                        f"{path}:{getattr(node, 'lineno', 0)}: network import outside approved "
                        "data provider"
                    )
            if network_allowed and isinstance(node, ast.Call):
                function_name = ""
                if isinstance(node.func, ast.Name):
                    function_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    function_name = node.func.attr
                if function_name == "Request":
                    method_keywords = [item for item in node.keywords if item.arg == "method"]
                    if not method_keywords or not isinstance(
                        method_keywords[0].value, ast.Constant
                    ):
                        findings.append(
                            f"{path}:{node.lineno}: provider request method must be literal GET"
                        )
                    elif str(method_keywords[0].value.value).upper() != "GET":
                        findings.append(
                            f"{path}:{node.lineno}: provider uses forbidden HTTP write method"
                        )
                if function_name.lower() in {method.lower() for method in WRITE_HTTP_METHODS}:
                    findings.append(
                        f"{path}:{node.lineno}: provider exposes forbidden HTTP write call"
                    )
    if {mode.value for mode in TradingMode} != {"BACKTEST", "PAPER"}:
        findings.append("TradingMode contains a mode outside BACKTEST/PAPER")
    if "LIVE" in {state.value for state in StrategyState}:
        findings.append("StrategyState contains forbidden LIVE state")
    return findings


def main() -> None:
    findings = scan()
    if findings:
        raise SystemExit("Unsafe execution surface detected:\n" + "\n".join(findings))
    print(
        "Safety scan passed: only approved read-only market-data networking exists; "
        "no execution or funding surface detected."
    )


if __name__ == "__main__":
    main()
