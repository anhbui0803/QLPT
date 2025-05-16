from bson import ObjectId
from pydantic_core import core_schema


class ObjID(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v, *args, **kwargs):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return str(v)

    # @classmethod
    # def __modify_schema__(cls, field_schema):
    #     field_schema.update(type="string")

    @classmethod
    def __get_pydantic_json_schema__(cls, _core_schema, handler):
        return {"type": "string", "format": "object-id"}
