from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class WindowRequest(_message.Message):
    __slots__ = ("sensor_id", "pv", "op", "window_start_unix_ms")
    SENSOR_ID_FIELD_NUMBER: _ClassVar[int]
    PV_FIELD_NUMBER: _ClassVar[int]
    OP_FIELD_NUMBER: _ClassVar[int]
    WINDOW_START_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    sensor_id: str
    pv: _containers.RepeatedScalarFieldContainer[float]
    op: _containers.RepeatedScalarFieldContainer[float]
    window_start_unix_ms: int
    def __init__(self, sensor_id: _Optional[str] = ..., pv: _Optional[_Iterable[float]] = ..., op: _Optional[_Iterable[float]] = ..., window_start_unix_ms: _Optional[int] = ...) -> None: ...

class WindowResponse(_message.Message):
    __slots__ = ("label", "ellipse_index", "kano_verdict", "has_activity")
    LABEL_FIELD_NUMBER: _ClassVar[int]
    ELLIPSE_INDEX_FIELD_NUMBER: _ClassVar[int]
    KANO_VERDICT_FIELD_NUMBER: _ClassVar[int]
    HAS_ACTIVITY_FIELD_NUMBER: _ClassVar[int]
    label: str
    ellipse_index: float
    kano_verdict: bool
    has_activity: bool
    def __init__(self, label: _Optional[str] = ..., ellipse_index: _Optional[float] = ..., kano_verdict: _Optional[bool] = ..., has_activity: _Optional[bool] = ...) -> None: ...
