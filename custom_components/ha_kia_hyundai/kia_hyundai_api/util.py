import logging

from .const import SENSITIVE_FIELD_NAMES

_LOGGER = logging.getLogger(__name__)


# Keys are compared in lower case, so "blueLinkServicePin" matches whatever
# case the API or a header uses.
_SENSITIVE_FIELD_NAMES_LOWER = frozenset(name.lower() for name in SENSITIVE_FIELD_NAMES)


def clean_dictionary_for_logging(dictionary: dict[str, any]) -> dict[str, any]:
    mutable_dictionary = dictionary.copy()
    for key in dictionary:
        if key.lower() in _SENSITIVE_FIELD_NAMES_LOWER:
            mutable_dictionary[key] = "***"
        if type(mutable_dictionary[key]) is dict:
            mutable_dictionary[key] = clean_dictionary_for_logging(
                mutable_dictionary[key].copy()
            )
        if type(mutable_dictionary[key]) is list:
            new_array = []
            for item in mutable_dictionary[key]:
                if type(item) is dict:
                    new_array.append(clean_dictionary_for_logging(item.copy()))
                else:
                    new_array.append(item)
            mutable_dictionary[key] = new_array

    return mutable_dictionary
