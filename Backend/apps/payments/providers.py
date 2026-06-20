from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.payments.models import Payment, PaymentTransaction, Refund


class PaymentProviderError(Exception):
    pass


@dataclass
class ProviderPaymentResult:
    provider: str
    payment_id: str
    status: str
    provider_reference: str = ""
    client_secret: str = ""
    raw_response: dict | None = None


@dataclass
class ProviderRefundResult:
    provider: str
    refund_id: str
    status: str
    provider_reference: str = ""
    raw_response: dict | None = None


class BasePaymentProvider:
    provider = None

    def create_payment(self, payment: Payment) -> ProviderPaymentResult:
        raise NotImplementedError

    def capture_payment(
        self,
        payment: Payment,
        *,
        provider_reference: str = "",
        metadata: dict | None = None,
    ) -> Payment:
        raise NotImplementedError

    def refund_payment(
        self,
        refund: Refund,
        *,
        provider_reference: str = "",
        metadata: dict | None = None,
    ) -> Refund:
        raise NotImplementedError

    def parse_webhook(self, payload: dict, headers: dict | None = None) -> dict:
        raise NotImplementedError


class ManualPaymentProvider(BasePaymentProvider):
    provider = Payment.Provider.MANUAL

    def create_payment(self, payment: Payment) -> ProviderPaymentResult:
        if payment.provider != self.provider:
            raise ValidationError(
                {"provider": "Manual provider can only handle manual payments."}
            )

        PaymentTransaction.objects.create(
            payment=payment,
            transaction_type=PaymentTransaction.TransactionType.INITIATED,
            amount=payment.amount,
            currency=payment.currency,
            provider_reference=str(payment.id),
            is_successful=True,
            raw_response={
                "provider": self.provider,
                "mode": "manual",
            },
        )

        return ProviderPaymentResult(
            provider=self.provider,
            payment_id=str(payment.id),
            status=payment.status,
            provider_reference=str(payment.id),
            raw_response={
                "provider": self.provider,
                "mode": "manual",
            },
        )

    def capture_payment(
        self,
        payment: Payment,
        *,
        provider_reference: str = "",
        metadata: dict | None = None,
    ) -> Payment:
        return payment.capture(
            provider_reference=provider_reference or f"MANUAL-{payment.id}",
            metadata=metadata
            or {
                "provider": self.provider,
                "mode": "manual_capture",
            },
            commit_order=True,
        )

    def refund_payment(
        self,
        refund: Refund,
        *,
        provider_reference: str = "",
        metadata: dict | None = None,
    ) -> Refund:
        return refund.mark_succeeded(
            provider_reference=provider_reference or f"MANUAL-REFUND-{refund.id}",
            metadata=metadata
            or {
                "provider": self.provider,
                "mode": "manual_refund",
            },
        )

    def parse_webhook(self, payload: dict, headers: dict | None = None) -> dict:
        return {
            "provider": self.provider,
            "event_id": payload.get("event_id", ""),
            "event_type": payload.get("event_type", "manual.event"),
            "payload": payload,
            "headers": headers or {},
        }


class PlaceholderGatewayProvider(BasePaymentProvider):
    def create_payment(self, payment: Payment) -> ProviderPaymentResult:
        raise PaymentProviderError(
            f"{payment.provider} provider adapter is not implemented yet."
        )

    def capture_payment(
        self,
        payment: Payment,
        *,
        provider_reference: str = "",
        metadata: dict | None = None,
    ) -> Payment:
        raise PaymentProviderError(
            f"{payment.provider} provider adapter is not implemented yet."
        )

    def refund_payment(
        self,
        refund: Refund,
        *,
        provider_reference: str = "",
        metadata: dict | None = None,
    ) -> Refund:
        raise PaymentProviderError(
            f"{refund.payment.provider} provider adapter is not implemented yet."
        )

    def parse_webhook(self, payload: dict, headers: dict | None = None) -> dict:
        raise PaymentProviderError("Provider webhook adapter is not implemented yet.")


def get_payment_provider(provider):
    providers = {
        Payment.Provider.MANUAL: ManualPaymentProvider,
        Payment.Provider.STRIPE: PlaceholderGatewayProvider,
        Payment.Provider.PAYPAL: PlaceholderGatewayProvider,
        Payment.Provider.JAZZCASH: PlaceholderGatewayProvider,
        Payment.Provider.EASYPAISA: PlaceholderGatewayProvider,
        Payment.Provider.HBLPAY: PlaceholderGatewayProvider,
    }

    provider_class = providers.get(provider)

    if not provider_class:
        raise PaymentProviderError(f"Unsupported payment provider: {provider}")

    instance = provider_class()
    instance.provider = provider

    return instance


def create_manual_payment_for_order(
    *,
    order,
    created_by=None,
    metadata=None,
):
    payment = Payment.create_for_order(
        order=order,
        provider=Payment.Provider.MANUAL,
        amount=order.total_amount,
        created_by=created_by,
        metadata=metadata or {},
    )

    provider = get_payment_provider(Payment.Provider.MANUAL)
    provider.create_payment(payment)

    return payment


def capture_manual_payment(
    *,
    payment,
    provider_reference="",
    metadata=None,
):
    provider = get_payment_provider(Payment.Provider.MANUAL)

    return provider.capture_payment(
        payment,
        provider_reference=provider_reference,
        metadata=metadata or {},
    )