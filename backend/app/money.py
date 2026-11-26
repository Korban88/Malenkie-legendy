"""Positive money amounts; XTR and RUB are separate, non-convertible units."""
from dataclasses import dataclass
from typing import Literal


def _require_positive_int(value: int) -> None:
    if type(value) is not int:
        raise TypeError('Money amount must be an integer')
    if value <= 0:
        raise ValueError('Money amount must be positive')


@dataclass(frozen=True, slots=True)
class Money:
    """RUB minor units are kopeks; XTR minor units are whole Telegram Stars.

    Arithmetic and currency conversion are deliberately unsupported.
    """

    currency: Literal['RUB', 'XTR']
    minor_units: int

    def __post_init__(self) -> None:
        if self.currency not in ('RUB', 'XTR'):
            raise ValueError('Money currency must be RUB or XTR')
        _require_positive_int(self.minor_units)

    @classmethod
    def from_rubles(cls, amount_rub: int) -> 'Money':
        """Adapt the legacy API's whole rubles, validating before multiplication."""
        _require_positive_int(amount_rub)
        return cls(currency='RUB', minor_units=amount_rub * 100)

    def to_metadata(self) -> dict:
        return {'version': 1, 'currency': self.currency, 'minor_units': self.minor_units}
