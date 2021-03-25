"""This module contains inspection functionality for pydantic models.

"""
import functools
from collections import defaultdict
from itertools import chain
from typing import NamedTuple, Optional, Tuple, List, Dict, Any, Set
from pydantic import BaseModel
from pydantic.fields import ModelField


def is_pydantic_model(obj: Any) -> bool:
    """Determine if object is a valid pydantic model.

    """

    if isinstance(obj, type):
        return issubclass(obj, BaseModel)
    return False


def is_validator_by_name(name: str, obj: Any) -> bool:
    """Determine if a validator is present under provided`name` for given
    `model`.

    """

    if is_pydantic_model(obj):
        wrapper = ModelWrapper.factory(obj)
        return name in wrapper.get_validator_names()
    return False


class NamedReference(NamedTuple):
    """Contains the name and full path of an object.

    """

    name: str
    ref: str


class ValidatorFieldMapping(NamedTuple):
    """Contains single mapping of a pydantic validator and field.

    """

    validator: NamedReference
    field: NamedReference
    is_asterisk: bool = False


class ModelWrapper:
    """Wraps pydantic models and provides additional inpsection functionality on
    top of it.

    Parameters
    ----------
    model: pydantic.BaseModel
        The pydantic model for which validators field validator_field_mappings will be
        extracted.

    """

    CACHED: Dict[str, "ModelWrapper"] = {}

    def __init__(self, model: BaseModel):
        self.model = model
        self.validator_field_mappings = self.generate_mappings()

    def get_model_path(self) -> str:
        """Retrieve the full path to given model.

        """

        return f"{self.model.__module__}.{self.model.__name__}"

    def get_validators(self) -> Dict[str, List]:
        """Retrieves validators from pydantic model.

        """
        try:
            return self.model.__dict__["__validators__"]
        except KeyError:
            return {}

    def get_validator_names(self) -> Set[str]:
        """Collect all names of the validator functions.

        """

        validators = self.get_validators()
        return {validator.func.__name__
                for validator in chain.from_iterable(validators.values())}

    def get_reference(self, name: str):
        """Create reference path to given name.

        """

        return f"{self.get_model_path()}.{name}"

    def generate_mappings(self) -> Tuple[ValidatorFieldMapping]:
        """Inspects pydantic model and gathers all validator_field_mappings between validators
        and fields.

        """

        validators = self.get_validators()
        mappings = []

        # handle asterisk when single validator process all fields
        ignore_funcs = set()
        if "*" in validators:
            for validator in validators["*"]:
                func_name = validator.func.__name__
                ignore_funcs.add(func_name)
                for field in validators.keys():
                    _validator = NamedReference(
                        name=func_name,
                        ref=self.get_reference(func_name))
                    _field = NamedReference(
                        name=field,
                        ref=self.get_reference(field)
                    )
                    mapping = ValidatorFieldMapping(
                        validator=_validator,
                        field=_field,
                        is_asterisk=True
                    )
                    mappings.append(mapping)

            validators = {field: _validators
                          for field, _validators in validators.items()
                          if field != "*"}

        # handle standard validators
        for field, _validators in validators.items():
            for validator in _validators:
                func_name = validator.func.__name__
                if func_name in ignore_funcs:
                    continue

                _validator = NamedReference(
                    name=func_name,
                    ref=self.get_reference(func_name))
                _field = NamedReference(
                    name=field,
                    ref=self.get_reference(field)
                )
                mapping = ValidatorFieldMapping(
                    validator=_validator,
                    field=_field,
                    is_asterisk=False
                )
                mappings.append(mapping)

        return tuple(mappings)

    @functools.lru_cache(maxsize=128)
    def get_asterisk_validators(self) -> Dict[str, ValidatorFieldMapping]:
        """Get single validator field mapping per asterisk validator.

        """

        return {mapping.validator.name: mapping
                for mapping in self.validator_field_mappings
                if mapping.is_asterisk}

    @functools.lru_cache(maxsize=128)
    def get_standard_validators(self) -> Dict[str, List[ValidatorFieldMapping]]:
        """Get all validator field validator_field_mappings for standard validators.

        """

        result = defaultdict(list)
        for mapping in self.validator_field_mappings:
            if mapping.is_asterisk:
                continue
            result[mapping.validator.name].append(mapping)

        return result

    @classmethod
    def factory(cls, model: BaseModel) -> "ModelWrapper":
        """Factory with caching ability to prevent recreation of new instances.

        """

        model_id = id(model)
        result = cls.CACHED.get(model_id)
        if result:
            return result

        mapping = ModelWrapper(model)
        cls.CACHED[model_id] = mapping
        return mapping

    def get_fields_for_validator(self,
                                 validator_name: str) -> List[NamedReference]:
        """Return all fields for a given validator.

        """

        asterisk = self.get_asterisk_validators().get(validator_name)
        if asterisk:
            return [NamedReference("all fields", self.get_model_path())]

        else:
            return [NamedReference(x.field.name, x.field.ref)
                    for x in self.get_standard_validators()[validator_name]]

    def get_validators_for_field(self, field_name: str) -> List[NamedReference]:
        """Return all validators for given field.

        """

        return [x.validator for x in self.validator_field_mappings
                if x.field.name == field_name]

    def get_named_references_for_validators(self) -> List[NamedReference]:
        """Return named references for all validators.

        """

        unique = {mapping.validator.name: mapping
                  for mapping in self.validator_field_mappings}

        return [NamedReference(mapping.validator.name, mapping.validator.ref)
                for mapping in unique.values()]

    def get_all_field_properties(self) -> Dict[str, Dict]:
        """Return the field properties provided by schema.

        """

        return self.model.schema(by_alias=False)["properties"]

    def get_field_properties_by_name(self, field_name: str) -> Dict[str, Any]:
        """Return schema properties for given field name.

        """

        return self.get_all_field_properties()[field_name]

    def get_field_object_by_name(self, field_name: str) -> ModelField:
        """Return the field object for given field name.

        """

        return self.model.__dict__["__fields__"][field_name]