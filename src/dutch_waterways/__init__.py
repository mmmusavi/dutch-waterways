"""Route planner for Dutch inland waterways."""

from .data import default_network
from .network import Network, NoRouteError, Route, Snap, TooFarError, Vessel

__all__ = [
    "Network",
    "NoRouteError",
    "Route",
    "Snap",
    "TooFarError",
    "Vessel",
    "default_network",
    "od_matrix",
    "route",
]


def route(origin, destination, min_class=None, vessel=None, **kwargs) -> Route:
    """Route on the default network; see :meth:`Network.route`."""
    return default_network().route(origin, destination, min_class=min_class, vessel=vessel, **kwargs)


def od_matrix(places, min_class=None, vessel=None, **kwargs):
    """Distance matrix (km) on the default network; see :meth:`Network.od_matrix`."""
    return default_network().od_matrix(places, min_class=min_class, vessel=vessel, **kwargs)
