"""Pinned dual-stack host identity with the native routed RADIUS failure suite."""
import test_native_dual_stack_radius_integration as reference


class NativePinnedDualStackRadiusTests(reference.NativeDualStackRadiusTests):
    PINNED_HOST_KEY=True
