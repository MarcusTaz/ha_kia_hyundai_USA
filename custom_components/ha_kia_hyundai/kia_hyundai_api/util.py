import logging

from .const import SENSITIVE_FIELD_NAMES

_LOGGER = logging.getLogger(__name__)


def clean_dictionary_for_logging(dictionary: dict[str, any]) -> dict[str, any]:
    mutable_dictionary = dictionary.copy()
    for key in dictionary:
        if key.lower() in SENSITIVE_FIELD_NAMES:
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
