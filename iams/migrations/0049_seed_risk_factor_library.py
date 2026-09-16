# Audit Universe v2 — seed the default risk-factor library, a scoring model
# that uses it, and the default materiality metric registry.
#
# The factor set, weights, criteria and rating anchors below are taken from
# the IIA Global Practice Guide "Developing a Risk-Based Internal Audit Plan"
# (2nd ed., 2025), Appendix F "Example: Risk Assessment Using Risk Factor
# Approach", Figures F.1 and F.2. They are frozen inline rather than imported
# from application code so that later edits to the live library do not change
# what this migration seeds.
#
# The scoring model is created INACTIVE. Activating a model is a deliberate
# act with org-wide consequences (RiskScoringModel.save deactivates every
# other model), so it is left to an administrator rather than done by a
# deploy.
#
# Idempotent: every write is get_or_create/update_or_create keyed on a stable
# code, so a re-run is a no-op. Reversible: removes only what it created, and
# only when nothing references it.

from django.db import migrations

SCORING_MODEL_NAME = "IIA Baseline"
SCORING_MODEL_VERSION = "2.0"

# (code, name, group, weight, display_order, guidance, anchors)
RISK_FACTORS = [
    (
        "loss_exposure",
        "Loss / material exposure",
        "impact",
        50,
        1,
        "Dollar value at risk\n"
        "Annual operating expenses\n"
        "Number of transactions\n"
        "Impact on other areas of the organization\n"
        "Degree of reliance on IT",
        {
            "5": "High exposure.",
            "4": "Above average exposure.",
            "3": "Average exposure.",
            "2": "Less than average exposure.",
            "1": "Little exposure.",
        },
    ),
    (
        "strategic_risk",
        "Strategic risk",
        "impact",
        50,
        2,
        "Public perception / reputation\n"
        "Local economic conditions\n"
        "Volatility\n"
        "Significance to strategy\n"
        "Degree of external regulation\n"
        "Recent change in legislation or regulatory scrutiny\n"
        "Changes in business lines or services\n"
        "Significant new contracts",
        {
            "5": "High risk.",
            "4": "Above average risk.",
            "3": "Average risk.",
            "2": "Less than average risk.",
            "1": "Low risk.",
        },
    ),
    (
        "control_environment",
        "Control environment",
        "likelihood",
        35,
        3,
        "Degree of process isolation\n"
        "Degree of formalization and alignment of objectives\n"
        "New process/system implementation\n"
        "In-house vs. third-party process\n"
        "Operational management turnover\n"
        "Degree of performance monitoring in place\n"
        "Tone at the top\n"
        "Formality of processes/procedures\n"
        "Impact on customers",
        {
            "5": "High risk (very weak control environment).",
            "4": "Above average risk (weak control environment).",
            "3": "Average (average control environment).",
            "2": "Below average risk (strong control environment).",
            "1": "Low risk (very strong control environment).",
        },
    ),
    (
        "complexity",
        "Complexity",
        "likelihood",
        35,
        4,
        "Degree of automation\n"
        "Degree of specialization required to perform\n"
        "Level of technical detail\n"
        "Complexity of structure, architecture involved\n"
        "Frequency of change",
        {
            "5": "Highly complex.",
            "4": "Above average complexity.",
            "3": "Average complexity.",
            "2": "Less than average complexity.",
            "1": "Simple.",
        },
    ),
    (
        "assurance_coverage",
        "Assurance coverage",
        "likelihood",
        20,
        5,
        "Type of engagement\n"
        "Other reviews (external, regulatory)\n"
        "Second-line coverage\n"
        "Follow-up already in place",
        {
            "5": "Not reviewed in the last 4 years (3 years for compliance or high-impact risks).",
            "4": "Not reviewed in last 3 to 4 years (2 to 3 years for compliance or high-impact risks).",
            "3": "Reviewed in last 2 to 3 years (1 to 2 years for compliance or high-impact risks).",
            "2": "Reviewed in last 1 to 2 years (1 year for compliance, high impact).",
            "1": "Reviewed in the last year, or an initiative is in place currently.",
        },
    ),
    (
        "management_awareness",
        "Management awareness",
        "likelihood",
        10,
        6,
        "Concerns expressed in responses to surveys\n"
        "Concerns expressed in interviews\n"
        "Level of risk awareness",
        {
            "5": "Management concerned, has specific issue and reason.",
            "4": "Management has general concerns.",
            "3": "Management is neutral.",
            "2": "Management has no specific concerns.",
            "1": "Management can demonstrate effective control over risks.",
        },
    ),
]

# (code, label, unit, currency, applies_to, feeds_factor_code, order, active, description)
MATERIALITY_METRICS = [
    ("annual_revenue", "Annual revenue", "currency", "USD", [], "loss_exposure", 1, True,
     "Revenue attributable to this unit for the stated period."),
    ("annual_expenses", "Annual operating expenses", "currency", "USD", [], "loss_exposure", 2, True,
     "Operating expenditure run through this unit."),
    ("payroll_cost", "Payroll cost", "currency", "USD", [], "loss_exposure", 3, True,
     "Total employment cost carried by this unit."),
    ("total_assets", "Total assets", "currency", "USD", [], "loss_exposure", 4, True,
     "Book value of assets under this unit's control."),
    ("headcount", "Staff count", "fte", "", [], "complexity", 5, True,
     "Full-time equivalents working in this unit."),
    ("transaction_volume", "Annual transaction volume", "count", "", [], "loss_exposure", 6, True,
     "Count of transactions processed per year."),
    # Sector-specific — seeded inactive so a non-insurer never sees them.
    ("gross_written_premium", "Gross written premium", "currency", "USD", [], "loss_exposure", 10, False,
     "Insurance: gross written premium for the period."),
    ("claims_paid", "Claims paid", "currency", "USD", [], "loss_exposure", 11, False,
     "Insurance: claims settled during the period."),
    ("outstanding_reserves", "Outstanding claim reserves", "currency", "USD", [], "loss_exposure", 12, False,
     "Insurance: carried reserves including IBNR."),
]


def forwards(apps, schema_editor):
    RiskFactor = apps.get_model("iams", "RiskFactor")
    RiskScoringModel = apps.get_model("iams", "RiskScoringModel")
    RiskFactorWeight = apps.get_model("iams", "RiskFactorWeight")
    MetricDef = apps.get_model("iams", "MaterialityMetricDefinition")

    factors = {}
    for code, name, group, _weight, order, guidance, anchors in RISK_FACTORS:
        factor, _created = RiskFactor.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "group": group,
                "guidance": guidance,
                "rating_anchors": anchors,
                "display_order": order,
                "scale_min": 1,
                "scale_max": 5,
                "is_active": True,
            },
        )
        # Backfill the v2 columns on a factor that already existed under this
        # code from an earlier manual setup, without touching its name or
        # scale (an admin may have tuned those deliberately).
        dirty = []
        if not factor.group or factor.group == "standalone":
            factor.group = group
            dirty.append("group")
        if not factor.guidance:
            factor.guidance = guidance
            dirty.append("guidance")
        if not factor.rating_anchors:
            factor.rating_anchors = anchors
            dirty.append("rating_anchors")
        if not factor.display_order:
            factor.display_order = order
            dirty.append("display_order")
        if dirty:
            factor.save(update_fields=dirty)
        factors[code] = factor

    model, _created = RiskScoringModel.objects.get_or_create(
        name=SCORING_MODEL_NAME,
        version=SCORING_MODEL_VERSION,
        defaults={
            "description": (
                "Default risk-factor model following the IIA Global Practice "
                "Guide 'Developing a Risk-Based Internal Audit Plan' (2nd ed.), "
                "Appendix F. Impact-related factors (loss exposure, strategic "
                "risk) and likelihood-related factors (control environment, "
                "complexity, assurance coverage, management awareness) are "
                "weighted into two subtotals and combined. Seeded inactive — "
                "activate it from Settings once the weights have been reviewed "
                "against your organization's risk profile."
            ),
            "formula": "impact_likelihood",
            "high_risk_threshold": 60,
            "is_active": False,
        },
    )

    for code, _name, _group, weight, *_rest in RISK_FACTORS:
        RiskFactorWeight.objects.get_or_create(
            scoring_model=model,
            factor=factors[code],
            defaults={"weight": weight},
        )

    for (code, label, unit, currency, applies_to, feeds, order, active, desc) in MATERIALITY_METRICS:
        MetricDef.objects.get_or_create(
            code=code,
            defaults={
                "label": label,
                "description": desc,
                "unit": unit,
                "currency": currency,
                "applies_to": applies_to,
                "feeds_factor": factors.get(feeds),
                "display_order": order,
                "is_active": active,
            },
        )


def backwards(apps, schema_editor):
    RiskFactor = apps.get_model("iams", "RiskFactor")
    RiskScoringModel = apps.get_model("iams", "RiskScoringModel")
    RiskFactorWeight = apps.get_model("iams", "RiskFactorWeight")
    MetricDef = apps.get_model("iams", "MaterialityMetricDefinition")
    EntityRiskScore = apps.get_model("iams", "EntityRiskScore")
    EntityMaterialityValue = apps.get_model("iams", "EntityMaterialityValue")

    model = RiskScoringModel.objects.filter(
        name=SCORING_MODEL_NAME, version=SCORING_MODEL_VERSION,
    ).first()
    # Refuse to remove a model that has already scored something — the
    # snapshots reference it via PROTECT and, more to the point, deleting it
    # would discard assessment history.
    if model is not None and not EntityRiskScore.objects.filter(
        scoring_model=model,
    ).exists():
        model.factor_weights.all().delete()
        model.delete()

    used_metric_ids = set(
        EntityMaterialityValue.objects.values_list("definition_id", flat=True)
    )
    MetricDef.objects.filter(
        code__in=[m[0] for m in MATERIALITY_METRICS],
    ).exclude(pk__in=used_metric_ids).delete()

    # Remove seeded factors that nothing weights any more.
    #
    # Dependents are cleared explicitly and the rows are then removed with
    # _raw_delete, which bypasses Django's cascade collector. The collector
    # cannot run here: RiskScoringModel.factors is a ManyToManyField through
    # RiskFactorWeight, and resolving that through-relation from inside a
    # historical model state mixes the migration's RiskFactor with the real
    # one, raising "Cannot query RiskFactor object: Must be RiskFactor
    # instance". Clearing the dependents first makes the raw delete safe --
    # by this point nothing references these rows.
    seeded_codes = [f[0] for f in RISK_FACTORS]
    orphan_ids = list(
        RiskFactor.objects
        .filter(code__in=seeded_codes, weights__isnull=True)
        .values_list("pk", flat=True)
    )
    if orphan_ids:
        MetricDef.objects.filter(feeds_factor_id__in=orphan_ids).update(feeds_factor=None)
        RiskFactorWeight.objects.filter(factor_id__in=orphan_ids).delete()
        RiskFactor.objects.filter(pk__in=orphan_ids)._raw_delete(
            RiskFactor.objects.db,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0048_risk_override_access"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
