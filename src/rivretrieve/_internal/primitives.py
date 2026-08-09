from typing import Literal, NewType

OnIssue = Literal["warn", "raise", "ignore"]
IssueSeverity = Literal["info", "warning", "error"]

ProviderId = NewType("ProviderId", str)
ProductId = NewType("ProductId", str)
