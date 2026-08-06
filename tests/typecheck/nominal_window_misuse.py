from rivretrieve._internal.engine import FetchWindow, RequestedWindow


def clip(window: RequestedWindow) -> None:
    pass


def misuse(fetch_window: FetchWindow) -> None:
    clip(fetch_window)
