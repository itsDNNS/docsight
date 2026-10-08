"""Helpers for the Correlation view."""


def wait_for_correlation(page):
    """Wait until the correlation chart has drawn its data."""
    page.wait_for_function(
        """() => document.getElementById('correlation-loading').hidden
            && !document.getElementById('correlation-chart-container').hidden
            && !!window._corrChartState"""
    )
