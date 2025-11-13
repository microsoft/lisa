# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import html
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.messages import MessageBase, TestResultMessage, TestRunMessage, TestRunStatus
from lisa.notifier import Notifier
from lisa.secret import mask
from lisa.util import LisaException, constants


@dataclass_json()
@dataclass
class HtmlSchema(schema.Notifier):
    path: str = "lisa.html"
    """
    open html report in browser for convenient at local
    """
    auto_open: bool = False


class Html(Notifier):
    """
    This class generates a beautiful HTML report.
    """

    @classmethod
    def type_name(cls) -> str:
        return "html"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return HtmlSchema

    def finalize(self) -> None:
        runbook = cast(HtmlSchema, self.runbook)
        self._log.info(f"report: {self._report_path}")
        self._write_html_report()
        if runbook.auto_open:
            import webbrowser

            webbrowser.open(f"file://{self._report_path}")

    def _received_message(self, message: MessageBase) -> None:
        if isinstance(message, TestRunMessage):
            self._received_test_run(message)
        elif isinstance(message, TestResultMessage):
            self._received_test_result(message)
        else:
            raise LisaException(f"received unknown message type: {message}")

    def _received_test_run(self, message: TestRunMessage) -> None:
        if message.status == TestRunStatus.INITIALIZING:
            self._title = message.run_name
            metadata_dict = {
                "test project": message.test_project,
                "test pass": message.test_pass,
                "tags": message.tags,
                "runbook_path": constants.RUNBOOK_FILE,
                "runbook": mask(constants.RUNBOOK),
            }
            # Filter out None/empty values
            self._metadata = OrderedDict(
                {key: value for key, value in metadata_dict.items() if value}
            )
        elif message.status == TestRunStatus.FAILED:
            self._collection_errors.append(
                {"nodeid": "run failed", "message": message.message}
            )

    def _received_test_result(self, message: TestResultMessage) -> None:
        # Store or overwrite result indexed by test ID
        self._test_results[message.id_] = message

    def _subscribed_message_type(self) -> List[Type[MessageBase]]:
        return [TestResultMessage, TestRunMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(HtmlSchema, self.runbook)
        self._report_path = constants.RUN_LOCAL_LOG_PATH / runbook.path
        self._test_results: Dict[str, TestResultMessage] = {}
        self._collection_errors: List[Dict[str, str]] = []
        self._title = "LISA Test Report"
        self._metadata = OrderedDict()
        self._start_time = datetime.now(timezone.utc)

    def _write_html_report(self) -> None:
        """Generate and write the HTML report."""
        # Calculate statistics
        test_results_list = list(self._test_results.values())
        total = len(test_results_list)
        passed = sum(1 for r in test_results_list if r.status.name.lower() == "passed")
        failed = sum(1 for r in test_results_list if r.status.name.lower() == "failed")
        skipped = sum(
            1 for r in test_results_list if r.status.name.lower() == "skipped"
        )
        errors = len(self._collection_errors)
        duration = sum(r.elapsed for r in test_results_list)

        html_content = self._generate_html_from_template(
            total, passed, failed, skipped, errors, duration
        )

        # Write to file
        self._report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._report_path, "w", encoding="utf-8") as f:
            f.write(html_content)

    def _generate_html_from_template(
        self,
        total: int,
        passed: int,
        failed: int,
        skipped: int,
        errors: int,
        duration: float,
    ) -> str:
        """Generate the complete HTML content from template."""
        # Load template
        template_path = Path(__file__).parent / "html_template.html"
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        # Prepare template variables
        error_summary = (
            f', <span class="error count">{errors} errors</span>' if errors > 0 else ""
        )

        # Use string.Template for safe substitution (avoids CSS/JS brace conflicts)
        template = Template(template_content)
        html_content = template.substitute(
            title=html.escape(self._title),
            timestamp=self._start_time.strftime("%Y-%m-%d at %H:%M:%S UTC"),
            metadata_rows=self._generate_metadata_rows(),
            total=total,
            duration=f"{duration:.2f}",
            passed=passed,
            failed=failed,
            skipped=skipped,
            error_summary=error_summary,
            collection_error_rows=self._generate_collection_error_rows(),
            test_result_rows=self._generate_test_result_rows(),
        )

        return html_content

    def _generate_metadata_rows(self) -> str:
        """Generate HTML rows for metadata table."""
        rows = []
        for key, value in self._metadata.items():
            # Convert lists to comma-separated strings
            if isinstance(value, list):
                value_str = ", ".join(str(v) for v in value)
            else:
                value_str = str(value)
            rows.append(
                f"<tr><td>{html.escape(key)}</td>"
                f"<td>{html.escape(value_str)}</td></tr>"
            )
        return "\n".join(rows)

    def _generate_collection_error_rows(self) -> str:
        """Generate HTML rows for collection errors."""
        rows = []
        for error in self._collection_errors:
            rows.append(
                f"""<tr class="error">
<td class="col-result">ERROR</td>
<td class="col-name">{html.escape(error['nodeid'])}</td>
<td class="col-duration">N/A</td>
<td class="col-message">{html.escape(error['message'])}</td>
</tr>"""
            )
        return "\n".join(rows)

    def _generate_test_result_rows(self) -> str:
        """Generate HTML rows for test results."""
        # Sort results: unknown/other first, then failed, skipped, passed
        status_order = {"failed": 1, "skipped": 2, "passed": 3}
        sorted_results = sorted(
            self._test_results.values(),
            key=lambda r: status_order.get(r.status.name.lower(), 0),
        )

        rows = []
        for result in sorted_results:
            # Format duration as HH:MM:SS.fff
            hours = int(result.elapsed // 3600)
            minutes = int((result.elapsed % 3600) // 60)
            seconds = result.elapsed % 60
            duration_str = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

            status_str = result.status.name.lower()

            # Build information and analysis sections if available
            # Expand by default for failed and skipped tests
            extra_html = ""
            has_info = bool(result.information)
            has_analysis = bool(result.analysis)

            if has_info or has_analysis:
                # Expand by default for failed and skipped tests
                is_expanded = status_str in ["failed", "skipped"]
                extra_display = "block" if is_expanded else "none"
                arrow_symbol = "▼" if is_expanded else "▶"
                active_class = "active" if is_expanded else ""

                sections = []

                # Add information section
                if has_info:
                    info_lines = [
                        f"{html.escape(k)}: {html.escape(str(v))}"
                        for k, v in result.information.items()
                    ]
                    sections.append(
                        f"""
<div class="collapsible {active_class}" onclick="toggleExtra(this)">"""
                        f"""{arrow_symbol} Information</div>
<div class="extra" style="display: {extra_display};">
<pre>{'<br/>'.join(info_lines)}</pre>
</div>"""
                    )

                # Add analysis section
                if has_analysis:
                    analysis_lines = [
                        f"{html.escape(k)}: {html.escape(str(v))}"
                        for k, v in result.analysis.items()
                    ]
                    sections.append(
                        f"""
<div class="collapsible {active_class}" onclick="toggleExtra(this)">"""
                        f"""{arrow_symbol} Analysis</div>
<div class="extra" style="display: {extra_display};">
<pre>{'<br/>'.join(analysis_lines)}</pre>
</div>"""
                    )

                extra_html = f"""
<td colspan="4">
{''.join(sections)}
</td>"""

            message_display = html.escape(result.message) if result.message else ""

            rows.append(
                f"""<tr class="{status_str}">
<td class="col-result {status_str}">{status_str.upper()}</td>
<td class="col-name">{html.escape(result.id_)}:{html.escape(result.name)}</td>
<td class="col-duration">{duration_str}</td>
<td class="col-message">{message_display}</td>
</tr>"""
            )

            if extra_html:
                rows.append(f"<tr class='{status_str}'>" f"{extra_html}\n</tr>")

        return "\n".join(rows)
