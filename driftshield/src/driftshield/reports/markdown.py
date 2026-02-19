from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from driftshield.reports.models import ReportData, ReportType

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_markdown(report: ReportData) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template_name = {
        ReportType.FULL: "full.md.j2",
        ReportType.SUMMARY: "summary.md.j2",
    }.get(report.report_type, "full.md.j2")

    template = env.get_template(template_name)
    return template.render(report=report)
