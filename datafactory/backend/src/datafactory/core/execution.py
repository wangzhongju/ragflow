"""Control signals that column error policies must never swallow."""


class RunInterrupted(RuntimeError):
    """The attempt no longer owns the run."""


class BudgetExceeded(RuntimeError):
    """A reservation would exceed the run's budget."""


class BilledUnknown(RuntimeError):
    """A dispatched call cannot safely be repeated."""
