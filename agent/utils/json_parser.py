import json
import re
import logging

logger = logging.getLogger(__name__)


def robust_json_parse(text: str, fallback=None) -> dict:
    if not text:
        if fallback is not None:
            return fallback
        raise ValueError("Empty text provided")


    if isinstance(text, dict):
        return text


    text = text.strip()
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()


    start_idx = text.find('{')
    end_idx = text.rfind('}')

    if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
        if fallback is not None:
            logger.warning("No JSON found in text, using fallback")
            return fallback
        raise ValueError("No JSON found in response")

    json_str = text[start_idx:end_idx+1]


    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Direct JSON parse failed: {e}")

        error_pos = getattr(e, 'pos', 0)
        start = max(0, error_pos - 50)
        end = min(len(json_str), error_pos + 50)
        logger.warning(f"Error context: ...{json_str[start:end]}...")


    try:
        json_str_cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
        result = json.loads(json_str_cleaned)
        logger.info("JSON parsed successfully after removing control characters")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed after cleaning: {e}")


    try:


        json_str_fixed = re.sub(r"'([^']*)'(\s*:\s*)", r'"\1"\2', json_str)
        json_str_fixed = re.sub(r':\s*\'([^\']*)\'', r': "\1"', json_str_fixed)
        result = json.loads(json_str_fixed)
        logger.info("JSON parsed successfully after fixing quotes")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed after fixing quotes: {e}")


    try:

        json_str_fixed = re.sub(r',(\s*[}\]])', r'\1', json_str)
        result = json.loads(json_str_fixed)
        logger.info("JSON parsed successfully after removing trailing commas")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed after removing trailing commas: {e}")


    try:

        def escape_newlines_in_strings(s):
            result = []
            in_string = False
            escape_next = False

            for i, char in enumerate(s):
                if escape_next:
                    result.append(char)
                    escape_next = False
                    continue

                if char == '\\':
                    result.append(char)
                    escape_next = True
                    continue

                if char == '"':
                    in_string = not in_string
                    result.append(char)
                    continue

                if in_string and char in ('\n', '\r', '\t'):

                    if char == '\n':
                        result.append('\\n')
                    elif char == '\r':
                        result.append('\\r')
                    elif char == '\t':
                        result.append('\\t')
                else:
                    result.append(char)

            return ''.join(result)

        json_str_fixed = escape_newlines_in_strings(json_str)
        result = json.loads(json_str_fixed)
        logger.info("JSON parsed successfully after smart escaping")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed after smart escaping: {e}")


    try:
        import json5
        result = json5.loads(json_str)
        logger.info("JSON parsed successfully using json5")
        return result
    except ImportError:
        logger.debug("json5 not available")
    except Exception as e:
        logger.warning(f"JSON5 parse failed: {e}")


    logger.error(f"All JSON parsing attempts failed. Full JSON:\n{json_str}")

    if fallback is not None:
        logger.warning("Using fallback value")
        return fallback

    raise ValueError(f"Failed to parse JSON after all attempts. Last error: {e}")


def extract_json_from_response(response, field_name="content") -> str:
    text = ""


    if hasattr(response, 'text'):
        text = response.text
    elif hasattr(response, field_name):
        content = getattr(response, field_name)
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'text':
                    text = item.get('text', '')
                    break
    elif isinstance(response, dict) and field_name in response:
        text = response[field_name]
    elif isinstance(response, str):
        text = response
    else:
        text = str(response) if response else ""

    return text


async def extract_json_from_async_response(response, field_name="content") -> str:
    text = ""


    if hasattr(response, '__aiter__'):
        async for chunk in response:
            if isinstance(chunk, str):
                text = chunk
            elif hasattr(chunk, field_name):
                content = getattr(chunk, field_name)
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get('type') == 'text':
                            text = item.get('text', '')
    else:

        text = extract_json_from_response(response, field_name)

    return text
