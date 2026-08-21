"""Fail CI if runtime code gains execution, funding, or unapproved network capability."""

import ast
from pathlib import Path

from app.data.providers import StooqReadOnlyProvider, YahooReadOnlyProvider
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
    "submit_order",
    "place_order",
    "create_external_order",
    "cancel_external_order",
    "set_leverage",
    "enable_margin",
    "borrow_asset",
    "open_broker_account",
}
FORBIDDEN_SETTINGS = {
    "broker_api_key",
    "broker_secret",
    "broker_password",
    "exchange_api_key",
    "exchange_secret",
    "exchange_password",
    "broker_access_token",
    "broker_refresh_token",
    "wallet_private_key",
    "funding_account",
    "margin_account",
}
NETWORK_IMPORTS = {"requests", "httpx", "aiohttp", "urllib", "http", "socket", "websockets"}
FORBIDDEN_SDK_IMPORTS = {
    "alpaca",
    "binance",
    "ccxt",
    "coinbase",
    "ib_insync",
    "ibapi",
    "krakenex",
    "oandapyV20",
    "web3",
}
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
            if isinstance(node, ast.Assign):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                if any(name.lower() in FORBIDDEN_SETTINGS for name in names):
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
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call) or not decorator.args:
                        continue
                    route = decorator.args[0]
                    if not isinstance(route, ast.Constant) or not isinstance(route.value, str):
                        continue
                    function = decorator.func
                    if (
                        route.value.startswith("/forward")
                        and isinstance(function, ast.Attribute)
                        and function.attr.lower() != "get"
                    ):
                        findings.append(f"{path}:{node.lineno}: Phase 3 API route must be GET-only")
    if {mode.value for mode in TradingMode} != {"BACKTEST", "PAPER"}:
        findings.append("TradingMode contains a mode outside BACKTEST/PAPER")
    if "LIVE" in {state.value for state in StrategyState}:
        findings.append("StrategyState contains forbidden LIVE state")
    return findings


def provider_findings() -> list[str]:
    findings: list[str] = []
    for provider in (YahooReadOnlyProvider(), StooqReadOnlyProvider()):
        capabilities = provider.provider_metadata().capabilities
        if not capabilities.read_only or capabilities.requires_secret:
            findings.append(f"{type(provider).__name__} must remain credential-free and read-only")
    return findings


def main() -> None:
    findings = [*scan(Path("app")), *scan(Path("scripts")), *provider_findings()]
    if findings:
        raise SystemExit("Unsafe execution surface detected:\n" + "\n".join(findings))
    print(
        "Safety scan passed: only approved read-only market-data networking exists; "
        "no execution or funding surface detected."
    )


if __name__ == "__main__":
    main()
