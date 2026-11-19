"""Conservative, offline guard for known underspecified food names.

Passing this guard does not prove species or nutrition compatibility. It only
prevents known category labels from gaining identity through a nutrition search.
Comparison normalization never changes the stored visual name or confidence.
"""

import math
import re
import unicodedata


_SEPARATORS = frozenset("()[]{}_,，、。:：;；-－·\"'「」『』【】〈〉《》“”‘’")
_GENERIC_NAMES = frozenset({
    "菜", "菜葉", "菜叶", "葉菜", "叶菜", "葉菜類", "叶菜类",
    "綠葉菜", "绿叶菜", "綠色葉菜", "绿色叶菜", "綠色菜葉", "绿色菜叶",
    "綠葉蔬菜", "绿叶蔬菜", "綠色葉菜類", "绿色叶菜类",
    "青菜", "蔬菜", "蔬菜類", "蔬菜类", "綠色蔬菜", "绿色蔬菜",
    "瓜類", "瓜类", "黃色瓜類", "黄色瓜类",
    "食物", "食品", "食材", "熟食", "未知食物", "不明食物", "未知食材", "不明食材",
    "尚未紀錄", "尚未记录", "不完整", "需補充資料", "需补充资料", "需確認", "需确认",
    "肉類", "肉类", "魚類", "鱼类",
    "food", "unknown", "unknownfood", "unidentifiedfood", "vegetable", "vegetables",
    "greens", "leafygreens", "leafyvegetable", "leafyvegetables",
    "greenvegetable", "greenvegetables", "greenleafyvegetable", "greenleafyvegetables",
})
# A visual region qualifier helps distinguish two detections, but does not add
# food identity. Keep these finite so real ingredient/flavour suffixes survive.
_LOCATION_SUFFIXES = (
    "左上格", "右上格", "左下格", "右下格", "左上", "右上", "左下", "右下",
)
_MODIFIERS = tuple(sorted({
    "清炒", "蒜炒", "蒜香", "蒜蓉", "熱炒", "热炒", "快炒", "拌炒", "炒",
    "川燙", "川烫", "汆燙", "汆烫", "清燙", "清烫", "水煮", "涼拌", "凉拌",
    "清蒸", "油煎", "香煎", "油炸", "烘烤", "燒烤", "烧烤",
    "滷", "卤", "燉", "炖", "煮", "燙", "烫", "蒸", "煎", "炸", "烤",
    "熟", "cooked", "raw", "prepared", "stirfried", "stirfry",
    "sauteed", "sautéed", "boiled", "blanched", "steamed", "fried", "roasted",
}, key=len, reverse=True))
_UNCERTAINTY_MARKERS = (
    "疑似", "不確定", "不确定", "不明", "未知", "不詳", "不详",
    "無法辨識", "無法辨認", "无法识别", "无法辨认", "未辨識", "未辨认",
    "未確認", "未确认", "待確認", "待确认",
)
_ENGLISH_UNCERTAINTY = re.compile(r"\b(?:unknown|unidentified|uncertain|possibly)\b")

VISION_IDENTITY_READY_CONFIDENCE = 0.75
_IDENTITY_VALUES = {
    "food_state": {"prepared", "raw", "dry"},
    "preparation_method": {"boiled", "stir_fried", "pan_fried", "deep_fried", "roasted",
                           "braised", "steamed", "mixed"},
    "components_scope": {"food_only", "noodles_only", "whole_dish_with_broth", "with_sides"},
}


def requires_food_identity_confirmation(name):
    """Return whether a name is invalid or a known generic/uncertain label.

    Only whole labels with controlled preparation modifiers are classified as
    generic. Specific names such as 生菜, 小白菜 and 清炒青江菜 remain eligible
    for the existing confidence, state, source and nutrition checks.
    """
    if not isinstance(name, str) or not name.strip() or len(name) > 300:
        return True
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in name):
        return True
    normalized = unicodedata.normalize("NFKC", name).casefold()
    if (any(marker in normalized for marker in _UNCERTAINTY_MARKERS)
            or _ENGLISH_UNCERTAINTY.search(normalized)):
        return True
    remaining = "".join(character for character in normalized
                        if not character.isspace() and character not in _SEPARATORS)
    while remaining:
        if remaining in _GENERIC_NAMES:
            return True
        if any(remaining == generic + location
               for generic in _GENERIC_NAMES for location in _LOCATION_SUFFIXES):
            return True
        for modifier in _MODIFIERS:
            if remaining.startswith(modifier):
                remaining = remaining[len(modifier):]
                break
            if remaining.endswith(modifier):
                remaining = remaining[:-len(modifier)]
                break
        else:
            return False
    return True


def vision_identity_needs_confirmation(item, *, minimum_confidence=None):
    """Derive identity uncertainty without treating uncertain weight as identity.

    Alternatives are synonyms in the vision contract, not competing species.
    Invalid model fields still fail closed through validation_issues.
    """
    confidence = item.get("confidence")
    threshold = VISION_IDENTITY_READY_CONFIDENCE
    if minimum_confidence is not None:
        if (isinstance(minimum_confidence, bool) or not isinstance(minimum_confidence, (int, float))
                or not math.isfinite(minimum_confidence) or minimum_confidence < 0
                or minimum_confidence > 1):
            return True
        threshold = max(threshold, minimum_confidence)
    return not (
        not isinstance(confidence, bool) and isinstance(confidence, (int, float))
        and math.isfinite(confidence) and threshold <= confidence <= 1
        and not item.get("validation_issues")
        and not requires_food_identity_confirmation(item.get("name_zh"))
        and all(isinstance(item.get(field), str) and item[field] in values
                for field, values in _IDENTITY_VALUES.items())
    )


def identity_attributes_are_known(item):
    """Require usable state/preparation/scope independently of name confidence."""
    return (
        isinstance(item, dict)
        and not item.get("validation_issues")
        and all(isinstance(item.get(field), str) and item[field] in values
                for field, values in _IDENTITY_VALUES.items())
    )


def web_identity_ready(item, *, minimum_confidence=None):
    """Require an explicit server decision plus current identity constraints.

    Old scan snapshots lack the decision and remain readable, but cannot gain
    web authority. The repository hash and scan token bind this decision.
    """
    source = item.get("identity_confirmation_source")
    if source is not None or "identity_confirmation_id" in item:
        confirmation_id = item.get("identity_confirmation_id")
        return (
            source == "user"
            and isinstance(confirmation_id, str) and bool(confirmation_id.strip())
            and len(confirmation_id) <= 256
            and not any(ord(char) < 32 or ord(char) == 127 for char in confirmation_id)
            and item.get("identity_confirmation_required") is False
            and not requires_food_identity_confirmation(item.get("name_zh"))
            and identity_attributes_are_known(item)
        )
    return (item.get("identity_confirmation_required") is False
            and not vision_identity_needs_confirmation(item, minimum_confidence=minimum_confidence))


__all__ = ["requires_food_identity_confirmation", "vision_identity_needs_confirmation",
           "identity_attributes_are_known", "web_identity_ready",
           "VISION_IDENTITY_READY_CONFIDENCE"]
