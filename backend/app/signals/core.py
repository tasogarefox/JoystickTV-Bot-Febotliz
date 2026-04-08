from typing import (
    NamedTuple, TypeAlias, TypeVar, Generic,
    ClassVar, Any, Iterable, Iterator, Generator, Callable,
    overload,
)
import abc
import dataclasses as dc
import enum
import random

T = TypeVar("T")
NumberT = TypeVar("NumberT", int, float)
SignalExprT = TypeVar("SignalExprT", bound="SignalExpr", default="SignalExpr")

Token: TypeAlias = str
Node: TypeAlias = list["Node | Token"]

MISSING = object()


# ==============================================================================
# Config

MIN_FRAME_DURATION: int = 100  # ms

MIN_FRAME_DURATION_STEP: int = MIN_FRAME_DURATION  # ms
MIN_FRAME_INTENSITY_STEP: int = 1  # %

DEFAULT_DURATION: int = 1000  # ms
DEFAULT_INTENSITY: int = 0  # %


# ==============================================================================
# Exceptions

class SignalError(Exception): pass

class SignalExprError(SignalError, ValueError): pass
class SignalParseError(SignalExprError): pass
class SignalBuildError(SignalParseError): pass
class SignalOperatorError(SignalBuildError): pass
class SignalUnexpectedTokenTypeError(SignalBuildError): pass

class SignalEvalError(SignalError): pass
class SignalVariableError(SignalEvalError): pass
class SignalUnknownPatternError(SignalEvalError): pass

class SignalContextError(SignalError): pass
class SignalContextLockedError(SignalContextError): pass


# ==============================================================================
# Enums

class Op(enum.Enum):
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"

class CacheMode(enum.Enum):
    EXPR = "expr"
    """Apply to the expression, re-evaluate each pass"""

    FRAMES = "frames"
    """Apply to the evaluated frames, reuse frames"""

    DEFAULT = EXPR


# ==============================================================================
# Named Tuples

class MinMax(NamedTuple, Generic[T]):
    min: T
    max: T


# ==============================================================================
# Signal Frame

class SignalTargetMode(enum.IntEnum):
    OVERRIDE = 0
    EXCLUSIVE = 1

class SignalTarget(NamedTuple):
    """
    Signal target device and device settings.
    """

    device: str
    """Target device name"""

    intensity: int
    """Target intensity in percent (0-100)"""

    def __str__(self) -> str:
        return f"{self.device}={self.intensity}%"

@dc.dataclass(frozen=True, slots=True)
class SignalFrame:
    """
    Single signal frame.
    """

    duration: int
    """Duration in milliseconds"""

    intensity: int
    """Intensity in percent (0-100)"""

    targets: tuple[SignalTarget, ...] = tuple()
    """Target devices"""

    mode: SignalTargetMode = SignalTargetMode.OVERRIDE
    """Target mode"""

    @classmethod
    def new_override(
        cls,
        duration: int,
        intensity: int,
        targets: Iterable[SignalTarget] = tuple(),
    ):
        return cls(
            duration,
            intensity,
            tuple(targets),
            SignalTargetMode.OVERRIDE,
        )

    @classmethod
    def new_exclusive(
        cls,
        duration: int,
        targets: Iterable[SignalTarget],
    ):
        return cls(
            duration,
            0,
            tuple(targets),
            SignalTargetMode.EXCLUSIVE,
        )

    def __post_init__(self):
        if self.mode == SignalTargetMode.EXCLUSIVE and not self.targets:
            raise SignalParseError("Exclusive frame must have at least one target")

    def __str__(self) -> str:
        if self.mode == SignalTargetMode.OVERRIDE:
            return (
                f"<{self.__class__.__name__}"
                f" {self.duration:,}ms"
                f" at {self.intensity}%"
                f" override {self.targets}"
                f">"
            )

        if self.mode == SignalTargetMode.EXCLUSIVE:
            return (
                f"<{self.__class__.__name__}"
                f" {self.duration:,}ms"
                f" exclusive"
                f" {self.targets}"
                f">"
            )

        return super().__str__()

    def __bool__(self) -> bool:
        if self.mode == SignalTargetMode.EXCLUSIVE and not self.targets:
            return False
        return self.duration > 0

    @property
    def is_override(self) -> bool:
        return self.mode == SignalTargetMode.OVERRIDE

    @property
    def is_exclusive(self) -> bool:
        return self.mode == SignalTargetMode.EXCLUSIVE

    def get_devices_names(self) -> set[str]:
        return {x.device for x in self.targets}

    def resolve_devices(self, all_devices: Iterable[str]) -> set[str]:
        return (
            set(all_devices) if self.is_override else
            set(x.device for x in self.targets if x.device in all_devices)
        )

    def with_duration(self, duration: int) -> "SignalFrame":
        return dc.replace(self, duration=duration)

    def with_intensity(self, intensity: int) -> "SignalFrame":
        return dc.replace(self, intensity=intensity)


# ==============================================================================
# Signal Context

@dc.dataclass(slots=True, kw_only=True)
class SignalConfig:
    """
    Signal config, shared between root and child contexts.
    """

    total_limit: int | None = None
    """Total duration limit in milliseconds"""

    min_intensity: int = 0
    """Minimum intensity in percent (0-100)"""
    max_intensity: int = 100
    """Maximum intensity in percent (0-100)"""

    min_duration_step: int = 200
    """Minimum step duration in milliseconds"""
    min_intensity_step: int = 2
    """Minimum step intensity in percent (0-100)"""

    patterns: dict[str, "SignalExpr"] = dc.field(default_factory=dict)
    """Dict of named pattern expressions"""

    rng: random.Random = dc.field(default_factory=random.Random)
    """Random number generator"""

    @property
    def sane_total_limit(self) -> int | None:
        if self.total_limit is None:
            return None
        return max(self.total_limit, MIN_FRAME_DURATION)

    @property
    def sane_min_intensity(self) -> int:
        return max(0, self.min_intensity)

    @property
    def sane_max_intensity(self) -> int:
        return min(100, self.max_intensity)

    @property
    def sane_min_duration_step(self) -> int:
        return max(self.min_duration_step, MIN_FRAME_DURATION_STEP)

    @property
    def sane_min_intensity_step(self) -> int:
        return max(self.min_intensity_step, MIN_FRAME_INTENSITY_STEP)

@dc.dataclass(slots=True, kw_only=True)
class SignalState:
    """
    Signal state accumulated between parent and child contexts.
    """

    total_duration: int = 0
    """Total duration in milliseconds"""

    cur_devices: set[str] = dc.field(default_factory=set)
    """Current device names"""

    last_expr: "SignalExpr | None" = None
    """Last evaluated expression"""

    last_frame: "SignalFrame | None" = None
    """Last emitted frame"""

    @property
    def last_frame_intensity(self) -> int | None:
        """Intensity of last emitted frame in percent (0-100). Defaults to None."""
        frame = self.last_frame
        return frame.intensity if frame is not None else None

    @property
    def last_frame_duration(self) -> int | None:
        """Duration of last emitted frame in milliseconds. Defaults to None."""
        frame = self.last_frame
        return frame.duration if frame is not None else None

    def copy(self) -> "SignalState":
        return dc.replace(self)

@dc.dataclass(slots=True, kw_only=True)
class SignalContext:
    """
    Signal context.
    """

    parent: "SignalContext | None" = None
    """Parent context. None for the root context."""

    config: SignalConfig
    """Config shared between root and child contexts"""

    state: SignalState = dc.field(default_factory=SignalState)
    """State accumulated between parent and child contexts"""

    variables: dict[str, Any] = dc.field(default_factory=dict)
    """Variables local to this context"""

    expr_count: int = dc.field(init=False, default=0)
    """Number of expressions evaluated in this context"""

    frame_count: int = dc.field(init=False, default=0)
    """Number of frames emitted in this context"""

    active_duration_expr: "DurationExpr | None" = dc.field(init=False, default=None)
    """Last evaluated DurationExpr in this or parent context"""

    active_duration: int = dc.field(init=False, default=DEFAULT_DURATION)
    """Duration in milliseconds usually produced by `active_duration_expr`"""

    _locked: bool = dc.field(init=False, default=False)
    """Whether this context is locked"""

    @property
    def locked(self) -> bool:
        """Whether this context is locked."""
        return self._locked

    @property
    def parents(self) -> Iterator["SignalContext"]:
        """Parent contexts iterator."""
        parent = self.parent
        while parent is not None:
            yield parent
            parent = parent.parent

    @property
    def rng(self) -> random.Random:
        """Random number generator."""
        return self.config.rng

    @property
    def prev_was_duration_expr(self) -> bool:
        """Whether the previous expression in this context is the active DurationExpr."""
        return self.state.last_expr is self.active_duration_expr is not None

    @overload
    def get_var(self, name: str, *, inherit: bool = True) -> Any: ...

    @overload
    def get_var(self, name: str, default: T = MISSING, *, inherit: bool = True) -> Any | T: ...

    def get_var(self, name: str, default: T = MISSING, *, inherit: bool = True) -> Any | T:
        """
        Get a context variable.
        If `default` is provided, return it if not found. Raise `SignalVariableError` otherwise.
        If `inherit` is True, also check the parent contexts.
        """
        value = self.variables.get(name, default)
        if value is not MISSING:
            return value

        if inherit and self.parent is not None:
            return self.parent.get_var(name, default, inherit=inherit)

        raise SignalVariableError(f"Variable '{name}' not found")

    def set_var(self, name: str, value: Any) -> None:
        self.variables[name] = value

    def eval(self, *exprs: "SignalExpr") -> Generator[SignalFrame, None, None]:
        """Evaluate an expression."""
        if self._locked:
            raise SignalContextLockedError("Context is locked")

        self._locked = True
        try:
            for expr in exprs:
                it = iter_limit_frame_duration(
                    expr._eval(self),
                    self.config.sane_total_limit,
                    start=self.state.total_duration,
                )

                for frame in it:
                    yield frame
                    self.state.total_duration += frame.duration
                    self.state.last_frame = frame
                    self.frame_count += 1

                self.state.last_expr = expr
                self.expr_count += 1

        finally:
            self._locked = False

    def make_cache(self, mode: CacheMode = CacheMode.DEFAULT) -> "SignalContextCache":
        """Make a signal context cache."""
        return SignalContextCache(self.make_child(), mode)

    def make_child(self) -> "SignalContext":
        """Make a child signal context."""
        return dc.replace(
            self,
            parent=self,
            state=self.state.copy(),
            variables={},
        )

@dc.dataclass(slots=True)
class SignalContextCache:
    """
    Signal context wrapper for caching evaluated frames according to `mode`.
    """

    ctx: SignalContext
    mode: CacheMode

    frames: list["SignalFrame"] | None = dc.field(init=False, default=None)

    def eval(self, *exprs: "SignalExpr") -> Generator[SignalFrame, None, None]:
        """Evaluate and possibly cache expressions."""
        if self.mode == CacheMode.EXPR:
            yield from self.ctx.eval(*exprs)
            return

        if self.mode == CacheMode.FRAMES:
            if self.frames is not None:
                yield from self.frames
                return

            # buffer frames as we yield them
            frames = self.frames = []
            for frame in self.ctx.eval(*exprs):
                frames.append(frame)
                yield frame

            return

        raise NotImplementedError(f"Unknown cache mode: {self.mode!r}")

    def clear(self) -> None:
        self.frames = None


# ==============================================================================
# Expression Base

class SignalExpr(abc.ABC):
    """
    Signal expression.
    """

    __slots__ = ()

    @abc.abstractmethod
    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        """Evaluate this expression, yielding frames."""
        raise NotImplementedError


# ==============================================================================
# Expression Mixins

class RandExprMixin(SignalExpr, Generic[NumberT]):
    """
    Mixin for generating random values
    """

    rand_min: NumberT
    rand_max: NumberT

    def __init__(self, vmin: NumberT, vmax: NumberT | None = None, **kwargs):
        self.rand_min = vmin
        self.rand_max = vmax if vmax is not None else vmin
        super().__init__(**kwargs)

    def rand_float(self, ctx: SignalContext) -> float:
        return ctx.rng.uniform(self.rand_min, self.rand_max)

    def rand_int(self, ctx: SignalContext) -> int:
        return safe_randint(int(self.rand_min), int(self.rand_max), rng=ctx.rng)

class MathOpExprMixin(SignalExpr):
    """
    Expression mixin for simple math operators
    """

    op: Op

    def __init__(self, op: Op, **kwargs):
        self.op = op
        super().__init__(**kwargs)

class ParentExprMixin(SignalExpr, Generic[SignalExprT]):
    """
    Expression mixin for expressions with a single child
    """

    child: SignalExprT

    def __init__(
        self,
        child: SignalExprT,
        **kwargs,
    ):
        if not isinstance(child, SignalExpr):
            raise TypeError(
                f"{self.__class__.__name__}:"
                f" expected child to be {self.__class__.__name__}"
                f", got {child.__class__.__name__}"
            )

        self.child = child
        super().__init__(**kwargs)

class CachableExprMixin(SignalExpr):
    """
    Expression mixin for caching evaluations
    """

    cache_mode: CacheMode

    def __init__(self, mode: CacheMode = CacheMode.DEFAULT, **kwargs) -> None:
        self.cache_mode = mode
        super().__init__(**kwargs)

    def make_cache(self, ctx: "SignalContext") -> "SignalContextCache":
        return ctx.make_cache(self.cache_mode)


# ==============================================================================
# Expression Modifiers

class SignalModExpr(SignalExpr):
    """
    Signal modifier expression.
    """

class DurationExpr(SignalModExpr, RandExprMixin[int]):
    """
    Set duration for following expressions
    """

    def __str__(self) -> str:
        vmin = self.rand_min
        vmax = self.rand_max
        if vmin == vmax:
            return f"{vmin/1000:g}s"
        return f"{vmin/1000:g}-{vmax/1000:g}s"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        ctx.active_duration_expr = self
        ctx.active_duration = max(0, self.rand_int(ctx))
        yield from ()


# ==============================================================================
# Expression Transforms

class SignalTransExpr(ParentExprMixin[SignalExpr], CachableExprMixin):
    """
    Signal transform expression.
    """

    def __init__(
        self,
        child: "SignalExpr",
        *,
        mode: CacheMode = CacheMode.DEFAULT,
        **kwargs
    ) -> None:
        super().__init__(child=child, mode=mode, **kwargs)

class RepeatTransExpr(SignalTransExpr, RandExprMixin[int]):
    """
    Repeat child expression a given number of times.
    """

    def __init__(
        self,
        child: SignalExpr,
        vmin: int = 1,
        vmax: int | None = None,
        *,
        mode: CacheMode = CacheMode.DEFAULT
    ):
        super().__init__(
            child=child,
            vmin=vmin,
            vmax=vmax,
            mode=mode,
        )

    def __str__(self) -> str:
        return f"{self.child} * {self.rand_min}-{self.rand_max}"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        count = self.rand_int(ctx)
        if count <= 0:
            return

        cache = self.make_cache(ctx)
        for _ in range(count):
            yield from cache.eval(self.child)

class TimedRepeatTransExpr(SignalTransExpr, RandExprMixin[int], MathOpExprMixin):
    """
    Repeat child expression for a given duration.
    """

    def __init__(
        self,
        child: SignalExpr,
        vmin: int = DEFAULT_DURATION,
        vmax: int | None = None,
        *,
        op: Op = Op.MUL,
        mode: CacheMode = CacheMode.DEFAULT
    ):
        if op not in {Op.MUL, Op.ADD, Op.SUB}:
            raise SignalOperatorError(op)

        super().__init__(
            child=child,
            vmin=vmin,
            vmax=vmax,
            op=op,
            mode=mode,
        )

    def __str__(self) -> str:
        return f"{self.child} {self.op} {self.rand_min}-{self.rand_max}ms"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        op = self.op

        if op == Op.MUL:
            duration = self.rand_int(ctx)
            if duration <= 0:
                return

            cache = self.make_cache(ctx)
            yield from iter_repeat_frames_until_limit(
                lambda: cache.eval(self.child),
                duration + ctx.state.total_duration,
                start=ctx.state.total_duration,
            )

            return

        if op in {Op.ADD, Op.SUB}:
            offset = self.rand_int(ctx)
            if op == Op.SUB:
                offset = -offset

            cache = self.make_cache(ctx)
            yield from iter_repeat_frames_until_adjusted_duration(
                lambda: cache.eval(self.child),
                1,
                offset,
            )

            return

        raise SignalBuildError(f"{self.__class__.__name__}: invalid operator {op}")

class TimedScaleTransExpr(SignalTransExpr, RandExprMixin[int]):
    """
    Repeat child expression for a given duration.
    """

    def __init__(
        self,
        child: SignalExpr,
        vmin: int = DEFAULT_DURATION,
        vmax: int | None = None,
        *,
        mode: CacheMode = CacheMode.DEFAULT
    ):
        super().__init__(
            child=child,
            vmin=vmin,
            vmax=vmax,
            mode=mode,
        )

    def __str__(self) -> str:
        return f"{self.child} -> {self.rand_min}-{self.rand_max}ms"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        target_duration = self.rand_int(ctx)
        if target_duration <= 0:
            return

        frames = list(self.child._eval(ctx))
        frames_duration = sum(x.duration for x in frames)

        mult_duration = target_duration / frames_duration
        for i, frame in enumerate(frames):
            duration = int(frame.duration * mult_duration)
            if duration < MIN_FRAME_DURATION:
                # TODO: Merge instead of dropping short frames
                continue

            frames[i] = frame.with_duration(duration)

        yield from frames

class TipRepeatTransExpr(SignalTransExpr, RandExprMixin[float]):
    """
    Repeat child expression for a duration based on the tip amount:
        duration = tip_amount * 1000 * random(vmin, vmax)
    """

    SUFFIX: ClassVar[str] = "sec-per-token"

    def __init__(
        self,
        child: SignalExpr,
        vmin: float = 1,
        vmax: float | None = None,
        *,
        mode: CacheMode = CacheMode.DEFAULT,
    ):
        super().__init__(
            child=child,
            vmin=vmin,
            vmax=vmax,
            mode=mode,
        )

    def __str__(self) -> str:
        return f"{self.child} {self.rand_min:g}-{self.rand_max:g}{self.SUFFIX}"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        tip_amount = ctx.get_var("tip_amount", 0)
        if not isinstance(tip_amount, int):
            tip_amount = 0
        tip_amount = max(1, tip_amount)

        duration = round(tip_amount * 1000 * self.rand_float(ctx))

        cache = self.make_cache(ctx)
        yield from iter_repeat_frames_until_limit(
            lambda: cache.eval(self.child),
            duration + ctx.state.total_duration,
            start=ctx.state.total_duration,
        )

class MirrorTransExpr(SignalTransExpr):
    """
    Play child expression forward and then backward.
    """

    def __str__(self) -> str:
        token = "emirror" if self.cache_mode == CacheMode.EXPR else "fmirror"
        return f"{self.child} {token}"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        cache = self.make_cache(ctx)

        yield from cache.eval(self.child)

        rev = list(cache.eval(self.child))
        rev.reverse()
        yield from rev

class IntensityTransExpr(SignalTransExpr, RandExprMixin[int], MathOpExprMixin):
    """
    Adjust child expression intensity.
    """

    def __init__(
        self,
        child: SignalExpr,
        vmin: int = 1,
        vmax: int | None = None,
        *,
        op: Op = Op.MUL,
        mode: CacheMode = CacheMode.DEFAULT
    ):
        if op not in {Op.MUL, Op.DIV, Op.ADD, Op.SUB}:
            raise SignalOperatorError(op)

        super().__init__(
            child=child,
            vmin=vmin,
            vmax=vmax,
            op=op,
            mode=mode,
        )

    def __str__(self) -> str:
        return f"{self.child} {self.op} {self.rand_min}-{self.rand_max}%"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        op = self.op
        operand = self.rand_int(ctx)

        scale: float = 1
        offset: int = 0

        if op == Op.MUL:
            scale = operand / 100
        elif op == Op.DIV:
            scale = 100 / operand
        elif op == Op.ADD:
            offset = operand
        elif op == Op.SUB:
            offset = -operand
        else:
            raise SignalEvalError(f"{self.__class__.__name__}: invalid operator {op}")

        min_intensity = ctx.config.sane_min_intensity
        max_intensity = ctx.config.sane_max_intensity

        for frame in self.child._eval(ctx):
            intensity = round(frame.intensity * scale + offset)
            intensity = clamp(intensity, min_intensity, max_intensity)
            yield frame.with_intensity(intensity)


# ==============================================================================
# Expressions

class SequenceExpr(SignalExpr):
    """
    Sequence of expressions
    """

    items: list[SignalExpr]

    def __init__(self, items: Iterable[SignalExpr]):
        self.items = list(items)

    def __str__(self) -> str:
        return " ".join(str(x) for x in self.items)

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        subctx = ctx.make_child()
        for item in self.items:
            yield from subctx.eval(item)

class GroupExpr(SequenceExpr):
    """
    Group of expressions
    """

    def __str__(self) -> str:
        s = super().__str__()
        return f"({s})"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        subctx = ctx.make_child()

        if not ctx.prev_was_duration_expr:
            yield from subctx.eval(*self.items)
            return

        yield from iter_repeat_frames_until_limit(
            lambda: subctx.eval(*self.items),
            ctx.active_duration + subctx.state.total_duration,
            start=subctx.state.total_duration,
        )

class ChoiceExpr(SignalExpr):
    """
    Choose one of the given expressions
    """

    options: list[SignalExpr]

    def __init__(self, options: Iterable[SignalExpr]):
        self.options = list(options)

    def __str__(self) -> str:
        s = " | ".join(str(x) for x in self.options)
        return f"({s})"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        choice = ctx.rng.choice(self.options)
        yield from choice._eval(ctx)

class IntensityExpr(SignalExpr):
    """
    Generate frames according to provided intensities
    """

    intensities: list[tuple[int, int] | int | None]

    def __init__(self, intensities: Iterable[tuple[int, int] | int | None]):
        self.intensities = list(intensities)

    def __str__(self) -> str:
        parts = []

        for item in self.intensities:
            if isinstance(item, tuple):
                vmin, vmax = item
                parts.append(f"{vmin}" if vmin == vmax else f"{vmin}-{vmax}")

            elif item is None:
                parts.append("")

            else:
                parts.append(f"{item}% ")

        s = "..".join(parts)
        return f"{s}%"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        # Ensure we have at least one intensity
        intensities_ranges = self.intensities
        if not intensities_ranges:
            return

        # Ensure duration is non-zero
        duration = ctx.active_duration
        if duration <= 0:
            return

        # Get parameters
        cfg = ctx.config
        min_intensity = cfg.sane_min_intensity
        max_intensity = cfg.sane_max_intensity
        min_intensity_step = cfg.sane_min_intensity_step
        min_duration_step = cfg.sane_min_duration_step
        devices = ctx.state.cur_devices

        # Get intensities
        intensities: list[int] = []
        prev_intensity: int = ctx.state.last_frame_intensity or DEFAULT_INTENSITY
        for item in intensities_ranges:
            if isinstance(item, tuple):
                # Generate random intensity
                intensity = safe_randint(item[0], item[1], rng=ctx.rng)
            elif item is None:
                # Use previous intensity
                intensity = prev_intensity
            else:
                # Use fixed intensity
                intensity = item

            # Clamp intensity
            intensity = min(max(min_intensity, intensity), max_intensity)

            intensities.append(intensity)

        # Normalize to at least 2 segments
        segments = (
            intensities if len(intensities) > 1
            else [intensities[0], intensities[0]]
        )

        seg_count = len(segments) - 1
        seg_duration = duration / seg_count

        for seg_idx in range(seg_count):
            start = segments[seg_idx]
            stop = segments[seg_idx + 1]

            # Determine number of steps for this segment
            count = max(1, int(min(
                abs(stop - start) / min_intensity_step + 1,
                seg_duration / min_duration_step,
            )))

            step_intensity = (stop - start) / (count - 1) if count > 1 else 0
            step_duration = round(seg_duration / count)

            # If flat, use midpoint
            if step_intensity == 0:
                start = (start + stop) / 2

            for i in range(count):
                intensity = round(start + step_intensity * i)

                if not devices:
                    frame = SignalFrame.new_override(step_duration, intensity)
                else:
                    frame = SignalFrame.new_exclusive(
                        step_duration,
                        (SignalTarget(x, intensity) for x in devices),
                    )

                yield frame

class NamedExpr(SignalExpr):
    """
    Evaluate a named pattern.
    """

    name: str

    def __init__(self, name: str):
        if not name:
            raise SignalParseError("Pattern name must not be empty")

        self.name = name

    def __str__(self) -> str:
        return f":{self.name}"

    def _eval(self, ctx: SignalContext) -> Generator[SignalFrame, None, None]:
        pattern = ctx.config.patterns.get(self.name)
        if pattern is None:
            raise SignalUnknownPatternError(f"Unknown named pattern: {self.name}")

        if not ctx.prev_was_duration_expr:
            yield from pattern._eval(ctx)
            return

        yield from iter_repeat_frames_until_limit(
            lambda: pattern._eval(ctx),
            ctx.active_duration + ctx.state.total_duration,
            start=ctx.state.total_duration,
        )


# ==============================================================================
# Generic Helpers

def clamp(val: NumberT, vmin: NumberT, vmax: NumberT) -> NumberT:
    return min(max(val, vmin), vmax)

def next_or_none(it: Iterator[T]) -> T | None:
    try:
        return next(it)
    except StopIteration:
        return None

def safe_randint(a: int, b: int, *, rng: random.Random = random.Random()) -> int:
    """Return a random integer between a and b, order doesn't matter."""
    if a > b:
        a, b = b, a
    return rng.randint(a, b)


# ==============================================================================
# Parse Helpers

def _parse_value_number(
    raw: str,
    number_parser: Callable[[str], T] = float,
    *,
    name: str,
) -> T:
    for ch in raw:
        if ch not in "0123456789.-":
            raise SignalParseError(f"Invalid symbol {ch!r} in {name} number: {raw}")

    try:
        return number_parser(raw)
    except ValueError:
        raise SignalParseError(f"Invalid {name} number: {raw}")

def _parse_value_range(
    raw: str,
    number_parser: Callable[[str], T] = float,
    *,
    name: str,
) -> MinMax[T]:
    min_part, _, max_part = raw.partition("-")

    min_val = _parse_value_number(
        min_part, number_parser, name=name,
    )

    if not max_part:
        max_val = min_val
    else:
        max_val = _parse_value_number(
            max_part, number_parser, name=name,
        )

    return MinMax(min_val, max_val)

def _parse_value_ramp(
    raw: str,
    number_parser: Callable[[str], T] = float,
    *,
    name: str,
) -> list[MinMax[T] | None]:
    ramp: list[MinMax[T] | None] = []

    parts = raw.split("..")
    if not parts:
        raise SignalParseError(f"Invalid empty {name} value")

    for i, part in enumerate(parts):
        if part == "":  # Leading ".."
            if i != 0:
                raise SignalParseError(f"Invalid empty {name} segment at index {i}")

            ramp.append(None)
            continue

        v = _parse_value_range(part, number_parser, name=name)
        ramp.append(v)

    return ramp

def match_suffix(token: str, suffixes: Iterable[str]) -> str | None:
    for suffix in suffixes:
        if token.endswith(suffix):
            return suffix
    return None

def _split_int_prefix(s: str) -> tuple[int | None, str]:
    """
    Split a leading integer from a string.

    Returns:
        (number, rest_of_string)
    """
    i = 0
    n = len(s)

    # skip leading whitespace
    while i < n and s[i].isspace():
        i += 1

    start = i

    # # optional sign
    # if i < n and s[i] in "+-":
    #     i += 1

    has_digits = False

    while i < n:
        c = s[i]

        if c.isdigit():
            has_digits = True
            i += 1
            continue

        break

    # reject cases without digits
    if not has_digits:
        return None, s

    num_str = s[start:i]
    rest = s[i:]

    try:
        return int(num_str), rest
    except ValueError:
        return None, s

def _split_float_prefix(s: str) -> tuple[float | None, str]:
    """
    Split a leading float from a string.

    Returns:
        (number, rest_of_string)
    """
    i = 0
    n = len(s)

    # skip leading whitespace
    while i < n and s[i].isspace():
        i += 1

    start = i

    # # optional sign
    # if i < n and s[i] in "+-":
    #     i += 1

    has_digits = False
    has_dot = False

    while i < n:
        c = s[i]

        if c.isdigit():
            has_digits = True
            i += 1
            continue

        if c == "." and not has_dot:
            has_dot = True
            i += 1
            continue

        break

    # reject cases without digits
    if not has_digits:
        return None, s

    # treat trailing dot as part of rest
    if has_dot and i > start and s[i - 1] == ".":
        i -= 1

    num_str = s[start:i]
    rest = s[i:]

    try:
        return float(num_str), rest
    except ValueError:
        return None, s


# ==============================================================================
# Eval Helpers

def limit_frame_duration(
    frame: SignalFrame,
    limit: int | None,
    *,
    start: int = 0,
) -> tuple[SignalFrame | None, bool]:
    """
    Ensure that emitting `frame` does not cause the cumulative
    duration (`start + frame.duration`) to exceed `limit`.

    ### Returns:
        tuple[SignalFrame | None, bool]:
        - frame: possibly truncated frame, or None if nothing should be emitted
        - stop: True if no further frames should be processed
    """
    if limit is None:
        return frame, False

    remaining = limit - start
    if remaining <= 0:
        return None, True

    if frame.duration <= remaining:
        return frame, False

    # # Drop too-small frames
    # if remaining < MIN_FRAME_DURATION:
    #     return None, True

    return frame.with_duration(remaining), True

def iter_limit_frame_duration(
    frames: Iterable[SignalFrame],
    limit: int | None,
    *,
    start: int = 0,
) -> Generator[SignalFrame, None, tuple[bool, int]]:
    """
    Iterate frames with a cumulative millisecond `limit`.

    Applies `limit_frame_duration` cumulatively, starting at `start`.

    ### Yields:
        SignalFrame:
            - A (possibly truncated) frame to be processed.

    ### Returns:
        tuple[bool, int]:
            - stop:
                True if iteration terminated early due to reaching the `limit`,
                False if all frames were consumed.
            - total:
                The final accumulated duration in milliseconds, including any
                emitted (possibly truncated) frames.
    """
    total = start

    for frame in frames:
        frame, stop = limit_frame_duration(
            frame, limit, start=total,
        )

        # Prevent infinite loops
        if total >= 3_600_000:  # 1 hour
            maximum_str = f"{limit:,}ms" if limit is not None else str(None)
            raise SignalEvalError(
                f"Cumulative frame duration exceeds 1 hour"
                f", maybe an infinite loop or bug?"
                f"; frame: {frame}, stop: {stop}"
                f", total: {total:,}ms, maximum: {maximum_str}"
            )

        if frame is None:
            return stop, total

        total += frame.duration
        yield frame

        if stop:
            return True, total

    return False, total

def iter_repeat_frames_until_limit(
    factory: Callable[[], Iterable[SignalFrame]],
    limit: int,
    *,
    start: int = 0,
) -> Generator[SignalFrame, None, int]:
    """
    Repeatedly evaluate a frame-producing callable while enforcing the cumulative `limit`.

    The `factory` is invoked repeatedly to produce fresh iterables of frames.
    These frames are yielded (possibly truncated) until the
    cumulative duration, starting at `start`, reaches `limit`.

    ### Yields:
        SignalFrame:
            Frames produced by the factory, possibly truncated to respect the limit.

    ### Returns:
        int:
            The final accumulated duration in milliseconds.
            This will typically be equal to `limit`, but may be less if:
            - the `factory` produces no frames or zero-duration frames
            - iteration makes no progress (eg. total duration doesn't increase)
    """
    total = start

    while True:
        stop, new_total = yield from iter_limit_frame_duration(
            factory(), limit, start=total,
        )

        if new_total <= total:
            return new_total

        total = new_total

        if stop:
            return total

def iter_repeat_frames_until_adjusted_duration(
    factory: Callable[[], Iterable[SignalFrame]],
    scale: float,
    offset: int,
) -> Generator[SignalFrame, None, None]:
    """
    Yield frames from `factory`, repeating until a target duration is reached.

    The target is computed from one full pass:
        target = original_duration * scale + offset

    Frames are streamed when possible, otherwise buffered to support shorter
    or negatively adjusted targets.

    Yields frames (possibly truncated) until the accumulated duration
    meets the target duration.
    """
    frames: tuple[SignalFrame, ...] | None = None
    orig_duration = 0
    cur_duration = 0

    if scale >= 1 and offset >= 0:
        for frame in factory():
            yield frame
            orig_duration += frame.duration
        cur_duration = orig_duration

    else:
        frames = tuple(factory())
        orig_duration = sum(x.duration for x in frames)

    target_duration = round(orig_duration * scale + offset)

    if frames is not None:
        cur_duration = yield from iter_repeat_frames_until_limit(
            lambda: frames or (),
            target_duration,
            start=cur_duration,
        )

        if cur_duration >= target_duration:
            return

    if orig_duration <= 0:
        return

    yield from iter_repeat_frames_until_limit(
        factory,
        target_duration,
        start=cur_duration,
    )


# ==============================================================================
# Expression Builder

class ExprBuilder:
    DURATION_SUFFIXES: ClassVar[dict[str, int]] = {
        "ms": 1,
        "s": 1000,
        "m": 60_000,
    }

    INTENSITY_SUFFIXES: ClassVar[set[str]] = {
        "%",
    }

    MIRROR_MODES: ClassVar[dict[str, CacheMode]] = {
        "mirror": CacheMode.FRAMES,
        "fmirror": CacheMode.FRAMES,
        "emirror": CacheMode.EXPR,
    }

    def tokenize(self, s: str) -> list[Token]:
        """Tokenize an expression string"""
        tokens = []
        buf = []

        def flush():
            if buf:
                tokens.append("".join(buf))
                buf.clear()

        for ch in s:
            if ch.isspace():
                flush()
            elif ch in "()|":
                flush()
                tokens.append(ch)
            else:
                buf.append(ch)

        flush()
        return tokens

    def parse_tokens(self, tokens: Iterable[Token]) -> Node:
        """Build a token tree from a list of tokens"""
        root = []
        stack = [root]

        for token in tokens:
            if token == "(":
                group = []
                stack[-1].append(group)
                stack.append(group)

            elif token == ")":
                if len(stack) == 1:
                    raise SignalParseError("Unmatched ')'")
                stack.pop()

            else:
                stack[-1].append(token)

        if len(stack) != 1:
            raise SignalParseError("Unmatched '('")

        return root

    def build(self, node: Node) -> SequenceExpr | ChoiceExpr:
        """Build an expression from a list of tokens"""
        if any(x.casefold() in {"|", "or"} for x in node if isinstance(x, str)):
            return self._build_choice(node)

        items: list[SignalExpr] = []

        expr_duration: DurationExpr | None = None
        expr_stack: list[SignalExpr] = []

        def flush() -> bool:
            nonlocal expr_duration, expr_stack

            if not expr_stack:
                return False  # nothing to do

            # Add duration
            if expr_duration is not None:
                items.append(expr_duration)

            # Add expressions
            items.extend(expr_stack)

            # Reset state
            expr_duration = None
            expr_stack.clear()

            return True

        it_tokens = iter(node)
        for token in it_tokens:
            if isinstance(token, list):  # nested group
                expr = self.build(token)
                expr_stack.append(GroupExpr([expr]))
                continue

            token_fold = token.casefold()

            if token_fold == "all":
                flush()
                expr_stack.append(GroupExpr(items))
                items.clear()
                continue

            if token in "*/+-":
                flush()

                opstr = token
                op = Op(opstr)
                expr = self._pop_expr(items, 1, f"Nothing to transform with {opstr!r}")

                next_token = next_or_none(it_tokens)
                if not isinstance(next_token, str):
                    raise SignalUnexpectedTokenTypeError(f"Expected transform operand after {opstr!r}")

                next_token_fold = next_token.casefold()

                try:
                    v = self._parse_duration_token(next_token)
                    if v is not None:
                        items.append(TimedRepeatTransExpr(expr, v.min, v.max, op=op))
                        continue

                    v = self._parse_intensity_token(next_token)
                    if v is not None:
                        items.append(IntensityTransExpr(expr, v.min, v.max, op=op))
                        continue

                    if next_token_fold.endswith(TipRepeatTransExpr.SUFFIX):
                        if op != Op.MUL:
                            raise SignalOperatorError

                        raw = next_token[:-len(TipRepeatTransExpr.SUFFIX)]
                        v = _parse_value_range(raw, float, name="tip-repeat multiplier")
                        if v is not None:
                            items.append(TipRepeatTransExpr(expr, v.min, v.max))
                            continue

                    if op != Op.MUL:
                        raise SignalOperatorError

                    v = _parse_value_range(next_token, int, name="repeats")
                    if v is not None:
                        items.append(RepeatTransExpr(expr, v.min, v.max))
                        continue

                except SignalOperatorError:
                    raise SignalOperatorError(f"Unsupported operator {opstr!r} for {next_token!r}")

                raise SignalBuildError(f"Expected duration or intensity after {opstr!r}")

            if token == "->":
                flush()

                opstr = token
                op = Op.MUL
                expr = self._pop_expr(items, 1, "Nothing to scale")

                next_token = next_or_none(it_tokens)
                if not isinstance(next_token, str):
                    raise SignalUnexpectedTokenTypeError(f"Expected duration after {opstr!r}")

                v = self._parse_duration_token(next_token)
                if v is not None:
                    items.append(TimedScaleTransExpr(expr, v.min, v.max))
                    continue

                raise SignalBuildError(f"Expected duration after {opstr!r}")

            if token.startswith(":"):
                name = token[1:]
                expr_stack.append(NamedExpr(name))
                continue

            if token_fold in self.MIRROR_MODES:
                flush()

                expr = self._pop_expr(items, 1, "Nothing to mirror")

                mode = self.MIRROR_MODES[token_fold]
                items.append(MirrorTransExpr(expr, mode=mode))
                continue

            v = self._parse_duration_token(token)
            if v is not None:
                if expr_duration is not None:
                    flush()

                expr_duration = DurationExpr(v.min, v.max)
                continue

            suffix = self._match_suffix(token, self.INTENSITY_SUFFIXES)
            if suffix:
                flush()

                raw = token[:-len(suffix)]
                intensities = _parse_value_ramp(raw, int, name="intensity-percent")

                if not intensities:
                    raise SignalBuildError(f"Invalid intensity-percent: {token}")

                expr_stack.append(IntensityExpr(intensities))
                continue

            suffix = self._match_suffix(token, {"x"})
            if suffix:
                flush()

                expr = self._pop_expr(items, None, "Nothing to repeat")

                raw = token[:-len(suffix)]
                vmin, vmax = _parse_value_range(raw, int, name="repeat")

                expr_stack.append(RepeatTransExpr(expr, vmin, vmax))
                continue

            suffix = self._match_suffix(token, {"S"})
            if suffix:
                flush()

                expr = self._pop_expr(items, None, "Nothing to duration-repeat")

                raw = token[:-len(suffix)]
                vmin, vmax = _parse_value_range(raw, int, name="duration-repeat")

                expr_stack.append(TimedRepeatTransExpr(expr, vmin, vmax))
                continue

            raise SignalBuildError(f"Invalid value or symbol: {token}")

        flush()

        return SequenceExpr(items)

    def _build_choice(self, node: Node) -> ChoiceExpr:
        options: list[SignalExpr] = []
        current: list[Node | Token] = []

        for token in node:
            if token == "|":
                options.append(self.build(current))
                current = []
            else:
                current.append(token)

        options.append(self.build(current))
        return ChoiceExpr(options)

    def parse(self, s: str) -> SignalExpr:
        """Parse an expression from a string"""
        tokens = self.tokenize(s)
        tree = self.parse_tokens(tokens)
        return self.build(tree)

    def eval(
        self,
        expr: SignalExpr,
        *,
        variables: dict[str, Any] | None = None,
        **config_kwargs,
    ) -> Generator["SignalFrame", None, None]:
        """Evaluate an expression"""
        config = SignalConfig(**config_kwargs)
        ctx = SignalContext(config=config, variables=variables or {})
        yield from ctx.eval(expr)

    @staticmethod
    def _match_suffix(token: str, suffixes: Iterable[str]) -> str | None:
        for suffix in suffixes:
            if token.endswith(suffix):
                return suffix
        return None

    @staticmethod
    def _pop_expr(
        items: list[SignalExpr],
        count: int | None,
        errmsg: str,
    ) -> SignalExpr:
        item_count = len(items)

        if count is None:
            count = max(1, item_count)

        if item_count < count:
            raise SignalBuildError(errmsg)

        popped = items[-count:]  # get
        items[-count:] = []  # remove

        if count == 1:
            return popped[0]

        return SequenceExpr(popped)

    @classmethod
    def _parse_duration_token(cls, token: Token) -> MinMax[int] | None:
        suffix = cls._match_suffix(token.casefold(), cls.DURATION_SUFFIXES.keys())
        if not suffix:
            return None

        scale = cls.DURATION_SUFFIXES[suffix]
        raw = token[:-len(suffix)]

        num_type = float if scale > 1 else int
        v = _parse_value_range(raw, num_type, name="duration")
        return MinMax(round(v.min * scale), round(v.max * scale))

    @classmethod
    def _parse_intensity_token(cls, token: Token) -> MinMax[int] | None:
        suffix = cls._match_suffix(token.casefold(), cls.INTENSITY_SUFFIXES)
        if not suffix:
            return None

        raw = token[:-len(suffix)]
        return _parse_value_range(raw, int, name="intensity")
