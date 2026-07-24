"""A-short 退市/风险警示状态的单一判定口径。

历史回放只使用已经按 as-of 解析出的证券简称；当前运行才使用当前
``list_status``/``delist_date``。调用方负责在输入进入本 helper 前完成
相应的 PIT 数据准备。
"""
from __future__ import annotations

from collections.abc import Mapping


def _field(row, key: str):
    """Return a row field without treating pandas ``NaN`` as text."""
    if isinstance(row, Mapping):
        value = row.get(key)
    else:
        try:
            value = row.get(key) if key in row.index else None
        except AttributeError:
            value = None
    if value is None:
        return ""
    try:
        if bool(value != value):  # NaN, without importing pandas in this shared helper.
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _name_flags(name: str) -> tuple[bool, bool]:
    upper = name.upper()
    # 只认证券简称开头的 ST/*ST；不把普通名称中间偶然出现的 ST 当风险。
    # A-share risk-name prefixes include unfinished-share-reform forms too.
    # Match only at the beginning so ordinary S names and embedded ST text
    # remain eligible.
    st_flag = upper.startswith(("ST", "*ST", "SST", "S*ST"))
    # 退市整理票的官方简称通常以“退”结尾；“退市风险警示”等明确文本也拦。
    delisting_warning = "退市" in name or name.endswith("退")
    return st_flag, delisting_warning


def derive_delisting_flags(row, *, historical: bool = False) -> dict:
    """Derive ``st_flag`` and ``delisting_warning`` with fail-closed metadata.

    ``historical=True`` means ``name`` is already the active name from the
    as-of ``namechange`` interval.  Current ``list_status`` and a later
    ``delist_date`` must not leak into that replay.
    """
    name = _field(row, "name")
    list_status = _field(row, "list_status").upper()
    delist_date = _field(row, "delist_date")

    if not name:
        return {"st_flag": None, "delisting_warning": None, "known": False}

    st_flag, name_delisting_warning = _name_flags(name)
    if historical:
        # The row name has already passed the as-of namechange PIT join.
        return {
            "st_flag": st_flag,
            "delisting_warning": name_delisting_warning,
            "known": True,
        }

    # A live row must carry the requested status field.  Missing provider
    # status is not silently converted to a safe false value.  Keep the
    # name-derived warning signal, while making the status-dependent ST field
    # nullable so downstream consumers can distinguish unknown from a
    # known-clear row and fail closed.
    if not list_status:
        return {
            "st_flag": None,
            "delisting_warning": name_delisting_warning,
            "known": False,
        }

    return {
        "st_flag": st_flag,
        "delisting_warning": bool(name_delisting_warning or list_status == "D" or delist_date),
        "known": True,
    }
