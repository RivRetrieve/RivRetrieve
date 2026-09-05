from typing import Literal, NewType

CacheMode = Literal["bypass", "reuse", "refresh"]

OnIssue = Literal["warn", "raise", "ignore"]
IssueSeverity = Literal["info", "warning", "error"]

ProviderId = NewType("ProviderId", str)
ProductId = NewType("ProductId", str)
