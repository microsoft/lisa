from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.transformer import Transformer

from .common_database import DatabaseMixin, DatabaseSchema


@dataclass_json
@dataclass
class GaVMSizeTransformerSchema(schema.Transformer, DatabaseSchema):
    location: str = ""


class GaVMSizeTransformer(DatabaseMixin, Transformer):
    """
    Its a Transformer that gets ga vm size list from a given location.
    """

    __vm_size_name = "list"
    _tables = ["AzureVMSize"]

    def __init__(
        self,
        runbook: GaVMSizeTransformerSchema,
        runbook_builder: RunbookBuilder,
        **kwargs: Any,
    ) -> None:
        DatabaseMixin.__init__(self, runbook, self._tables)
        Transformer.__init__(self, runbook, runbook_builder, **kwargs)

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return GaVMSizeTransformerSchema

    @classmethod
    def type_name(cls) -> str:
        return "ga_vm_size"

    @property
    def _output_names(self) -> List[str]:
        return [self.__vm_size_name]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        DatabaseMixin._initialize(self)
        self._log.debug(f"runbook is {self.runbook}")
        self.AzureVMSize = self.base.classes.AzureVMSize

    def _internal_run(self) -> Dict[str, Any]:
        runbook: GaVMSizeTransformerSchema = self.runbook
        session = self.create_session()
        ga_vmsize: List[Tuple[Any]] = (
            session.query(self.AzureVMSize.VMSize)
            .filter_by(Location=runbook.location)
            .filter_by(IsTestable=1)
            .filter_by(EnableTest=1)
            .filter(self.AzureVMSize.TestQuota > 0)
            .all()
        )
        self.commit_and_close_session(session)
        if len(ga_vmsize) > 0:
            vm_size = ",".join([x[0] for x in ga_vmsize])
        else:
            vm_size = ""
        self._log.debug(f"vm_size is {vm_size}")
        return {self.__vm_size_name: vm_size}
