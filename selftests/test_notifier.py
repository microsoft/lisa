# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Type
from unittest import TestCase

from assertpy import assert_that

from lisa import notifier, schema
from lisa.messages import MessageBase, TestRunMessage
from lisa.notifier import Notifier


class MockNotifierA(Notifier):
    """Mock notifier with tracking capabilities"""

    # Class-level list to track the order of message reception
    call_order: List[str] = []

    @classmethod
    def type_name(cls) -> str:
        return "MockNotifierA"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.Notifier

    def __init__(self, runbook: schema.TypedSchema) -> None:
        super().__init__(runbook=runbook)
        self.received_messages: List[MessageBase] = []

    def _subscribed_message_type(self) -> List[Type[MessageBase]]:
        return [TestRunMessage, MessageBase]

    def _received_message(self, message: MessageBase) -> None:
        self.received_messages.append(message)
        MockNotifierA.call_order.append("A")


class MockNotifierB(Notifier):
    """Another mock notifier with tracking capabilities"""

    # Class-level list to track the order of message reception
    call_order: List[str] = []

    @classmethod
    def type_name(cls) -> str:
        return "MockNotifierB"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.Notifier

    def __init__(self, runbook: schema.TypedSchema) -> None:
        super().__init__(runbook=runbook)
        self.received_messages: List[MessageBase] = []

    def _subscribed_message_type(self) -> List[Type[MessageBase]]:
        return [TestRunMessage, MessageBase]

    def _received_message(self, message: MessageBase) -> None:
        self.received_messages.append(message)
        MockNotifierB.call_order.append("B")


class NotifierPriorityTestCase(TestCase):
    def setUp(self) -> None:
        """Reset the global notifier state before each test"""
        # Clear the global notifier lists
        notifier._notifiers.clear()
        notifier._messages.clear()
        notifier._message_queue.clear()

        # Reset call order tracking
        MockNotifierA.call_order.clear()
        MockNotifierB.call_order.clear()

    def tearDown(self) -> None:
        """Clean up after each test"""
        notifier._notifiers.clear()
        notifier._messages.clear()
        notifier._message_queue.clear()
        MockNotifierA.call_order.clear()
        MockNotifierB.call_order.clear()

    def _verify_priority_ordering(
        self,
        priority_a: int,
        priority_b: int,
        expected_first_name: str,
        expected_second_name: str,
        expected_first_priority: int,
        expected_second_priority: int,
        message_type: Type[MessageBase],
    ) -> None:
        """
        Helper method to verify notifier priority ordering.

        Args:
            priority_a: Priority value for MockNotifierA
            priority_b: Priority value for MockNotifierB
            expected_first_name: Expected class name of first notifier
            expected_second_name: Expected class name of second notifier
            expected_first_priority: Expected priority of first notifier
            expected_second_priority: Expected priority of second notifier
            message_type: Message type to check for subscription ordering
        """
        runbook_a = schema.Notifier(type="MockNotifierA", priority=priority_a)
        runbook_b = schema.Notifier(type="MockNotifierB", priority=priority_b)

        # Disable system notifiers for this test
        original_system_notifiers = notifier._system_notifiers
        notifier._system_notifiers = []

        try:
            # Initialize with both runbooks
            notifier.initialize([runbook_a, runbook_b])

            # Verify that _notifiers list is ordered by priority
            assert_that(notifier._notifiers).is_length(2)
            assert_that(notifier._notifiers[0].runbook.priority).is_equal_to(
                expected_first_priority
            )
            assert_that(notifier._notifiers[1].runbook.priority).is_equal_to(
                expected_second_priority
            )
            assert_that(notifier._notifiers[0].__class__.__name__).is_equal_to(
                expected_first_name
            )
            assert_that(notifier._notifiers[1].__class__.__name__).is_equal_to(
                expected_second_name
            )

            # Verify that message type subscriptions are also ordered
            assert_that(notifier._messages[message_type]).is_length(2)
            assert_that(
                notifier._messages[message_type][0].runbook.priority
            ).is_equal_to(expected_first_priority)
            assert_that(
                notifier._messages[message_type][1].runbook.priority
            ).is_equal_to(expected_second_priority)

        finally:
            notifier._system_notifiers = original_system_notifiers

    def test_notifier_priority_ordering_low_first(self) -> None:
        """Test that notifiers are ordered by priority (lower priority first)"""
        self._verify_priority_ordering(
            priority_a=10,
            priority_b=20,
            expected_first_name="MockNotifierA",
            expected_second_name="MockNotifierB",
            expected_first_priority=10,
            expected_second_priority=20,
            message_type=TestRunMessage,
        )

    def test_notifier_priority_ordering_high_first(self) -> None:
        """Test that higher priority numbers come after lower priority numbers"""
        self._verify_priority_ordering(
            priority_a=100,
            priority_b=50,
            expected_first_name="MockNotifierB",
            expected_second_name="MockNotifierA",
            expected_first_priority=50,
            expected_second_priority=100,
            message_type=MessageBase,
        )

    def test_notifier_priority_same_priority(self) -> None:
        """Test that notifiers with the same priority maintain insertion order"""
        # Create runbooks with the same priority
        runbook_a = schema.Notifier(type="MockNotifierA", priority=100)
        runbook_b = schema.Notifier(type="MockNotifierB", priority=100)

        # Disable system notifiers for this test
        original_system_notifiers = notifier._system_notifiers
        notifier._system_notifiers = []

        try:
            # Initialize with A first, B second
            notifier.initialize([runbook_a, runbook_b])

            # Verify that both notifiers are present
            assert_that(notifier._notifiers).is_length(2)
            assert_that(notifier._notifiers[0].runbook.priority).is_equal_to(100)
            assert_that(notifier._notifiers[1].runbook.priority).is_equal_to(100)

            # With stable sort, insertion order should be maintained
            assert_that(notifier._notifiers[0].__class__.__name__).is_equal_to(
                "MockNotifierA"
            )
            assert_that(notifier._notifiers[1].__class__.__name__).is_equal_to(
                "MockNotifierB"
            )

        finally:
            notifier._system_notifiers = original_system_notifiers

    def test_notifier_default_priority(self) -> None:
        """Test that default priority is 100 as per schema"""
        # Create runbook without specifying priority (should default to 100)
        runbook = schema.Notifier(type="MockNotifierA")

        assert_that(runbook.priority).is_equal_to(100)
