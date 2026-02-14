"""Modem drivers package.

Each driver implements the Driver interface and handles authentication
and data fetching for a specific modem type.
"""

__all__ = ["interface", "loader", "fritzbox", "vodafone"]
