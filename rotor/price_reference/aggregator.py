"""Freshness-checking wrapper around one configured FX rate source."""

from __future__ import annotations

import time
from decimal import Decimal

from rotor.price_reference.models import ReferencePrice
from rotor.price_reference.sources import RateSource


class ReferenceUnavailable(RuntimeError):
    """Raised when the configured reference source cannot be used."""


class ReferencePriceOracle:
    """Fetch one quote-per-base reference and reject stale observations."""

    def __init__(self, source: RateSource, *, max_age_s: float | None = None) -> None:
        """Store the source adapter and maximum tolerated observation age."""
        # Source adapters are injected to keep HTTP/provider behavior testable.
        self.source = source
        # Freshness is enforced centrally so runners do not quote stale mids.
        # When no explicit override is given, each source carries its own window
        # (intraday providers reject after minutes; daily references tolerate
        # longer), falling back to 10 minutes for sources that declare none.
        if max_age_s is not None:
            self.max_age_s = float(max_age_s)
        else:
            self.max_age_s = float(getattr(source, "default_max_age_s", 600.0))

    def get(
        self, base: str, quote: str, *, amount: Decimal | None = None
    ) -> ReferencePrice:
        """Return the quote-per-base rate for an ISO pair.

        `amount` is the base-currency size being worked; it is forwarded to the
        source so amount-aware providers (Wise) can price the exact size.
        """
        # Normalize the pair label for consistent operator-facing errors.
        pair = f"{base.upper()}/{quote.upper()}"
        try:
            # Delegate provider-specific HTTP/parsing to the configured source.
            obs = self.source.quote(base, quote, amount=amount)
        except Exception as exc:
            # Wrap provider failures in one domain-level exception type.
            raise ReferenceUnavailable(
                f"{pair}: {self.source.name} failed ({type(exc).__name__}: {exc})"
            ) from exc

        # Compare wall-clock time to provider observation time.
        age_s = time.time() - obs.ts
        if age_s > self.max_age_s:
            raise ReferenceUnavailable(
                f"{pair}: {self.source.name} quote is stale age={age_s:.1f}s"
            )
        # Return a smaller quote-safe shape that drops provider-specific raw data.
        return ReferencePrice(
            pair=pair,
            rate=obs.rate,
            ts=obs.ts,
            source=obs.source,
        )
