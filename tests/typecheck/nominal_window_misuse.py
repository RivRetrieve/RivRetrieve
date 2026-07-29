from rivretrieve._internal.engine import FetchWindow, RequestedWindow, WindowEndpoint


def clip(window: RequestedWindow) -> None:
    pass


fetch_window = FetchWindow(
    start=WindowEndpoint(object()),
    end=WindowEndpoint(object()),
)
clip(fetch_window)
