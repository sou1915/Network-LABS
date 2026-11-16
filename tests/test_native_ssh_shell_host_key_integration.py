"""Pinned host trust composed with the real shell/accounting orphan journal suite."""
import test_native_ssh_radius_journal as reference


class NativePinnedSSHJournalTests(reference.NativeSSHJournalTests):
    PINNED_HOST_KEY=True
