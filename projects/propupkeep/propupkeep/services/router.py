from __future__ import annotations

from propupkeep.models.issue import IssueCategory, Urgency


class IssueRouter:
    _category_defaults: dict[IssueCategory, list[str]] = {
        IssueCategory.SAFETY: ["On-Call Safety Team", "Property Manager"],
        IssueCategory.ELECTRICAL: ["Licensed Electrical Vendor", "Maintenance Supervisor"],
        IssueCategory.PLUMBING: ["Plumbing Vendor", "Maintenance Team"],
        IssueCategory.HVAC: ["HVAC Vendor", "Maintenance Team"],
        IssueCategory.APPLIANCE: ["Appliance Vendor", "Maintenance Team"],
        IssueCategory.COSMETIC: ["Turn Team"],
        IssueCategory.GENERAL: ["Maintenance Team"],
    }

    _high_priority_recipients = ["Community Manager"]

    def route_recipients(self, category: IssueCategory, urgency: Urgency) -> list[str]:
        recipients = list(self._category_defaults.get(category, ["Maintenance Team"]))
        if urgency == Urgency.HIGH:
            recipients.extend(self._high_priority_recipients)
        return sorted(set(recipients))
