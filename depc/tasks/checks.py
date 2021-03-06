import time

from flask import json
from jinja2.exceptions import TemplateError

from depc.extensions import db, redis
from depc.models.checks import Check
from depc.models.rules import Rule
from depc.sources import BaseSource
from depc.sources.exceptions import UnknownStateException, BadConfigurationException
from depc.tasks import UnrecoverableError
from depc.templates import Template
from depc.utils.qos import compute_qos_from_bools


def execute_check(logger, check_id, result_key, variables, name, start, end):
    check = db.session.query(Check).get(check_id)
    if not check:
        raise UnrecoverableError("Check {} not found".format(check_id))

    logger.info(
        "[{0}] Executing check ({1})...".format(check.name, check.id),
        extra={"result_key": result_key},
    )

    source = check.source
    source_plugin = BaseSource.load_source(source.plugin, source.configuration)

    # Render every values in parameters
    logger.debug(
        "[{0}] Raw parameters : {1}".format(check.name, check.parameters),
        extra={"result_key": result_key},
    )
    template = Template(
        check=check,
        context={"name": name, "start": start, "end": end, "variables": variables},
    )

    start_time = time.time()
    error = None
    check_result = None

    try:
        parameters = template.render()
    except TemplateError as e:
        parameters = {}
        error = e
        logger.critical(
            "[{0}] {1}".format(check.name, str(error)), extra={"result_key": result_key}
        )
    else:
        logger.debug(
            "[{0}] Rendered parameters : {1}".format(check.name, parameters),
            extra={"result_key": result_key},
        )

        # Load the check
        check_plugin = source_plugin.load_check(
            check_name=check.type,
            parameters=parameters,
            name=name,
            start=start,
            end=end,
        )

        # Execute the check and compute the elapsed time
        try:
            check_result = check_plugin.execute()

        # There is no data returned by the check
        except UnknownStateException as e:
            error = e
            logger.warning(
                "[{0}] {1}".format(check.name, str(error)),
                extra={"result_key": result_key},
            )

        # Do not stop the chain if this check fails
        except (BadConfigurationException, Exception) as e:
            error = e
            logger.critical(
                "[{0}] {1}".format(check.name, str(error)),
                extra={"result_key": result_key},
            )

    # Display check duration
    duration = time.time() - start_time
    logger.debug(
        "[{0}] Check duration : {1}s".format(check.name, duration),
        extra={"result_key": result_key},
    )

    result = {
        "id": check.id,
        "name": check.name,
        "type": check.type,
        "parameters": parameters,
        "duration": duration,
        "qos": None,  # No QOS by default
    }

    if error or not check_result:
        result.update({"error": str(error)})
    else:
        result.update(check_result)

        if result["qos"]:
            logger.info(
                "[{0}] Check returned {1}%".format(check.name, check_result["qos"]),
                extra={"result_key": result_key},
            )
        else:
            logger.warning(
                "[{0}] No QOS returned by the check".format(
                    check.name, check_result["qos"]
                ),
                extra={"result_key": result_key},
            )

    return result


def validate_results(logger, checks, rule_id, result_key, context):
    rule = db.session.query(Rule).get(rule_id)
    result = {"checks": checks, "context": context}

    # Remove all checks with no QOS
    checks = [c for c in checks if c["qos"] is not None]

    if checks:

        result_rule = compute_qos_from_bools(booleans=[c["bools_dps"] for c in checks])
        result.update(result_rule)

        logger.info(
            "[{0}] Rule done".format(rule.name), extra={"result_key": result_key}
        )
        logger.info(
            "[{0}] Rule QOS is {1:.5f}%".format(rule.name, result["qos"]),
            extra={"result_key": result_key},
        )
    else:
        result["qos"] = "unknown"
        logger.warning(
            "[{0}] No QOS was found in any checks, so no QOS can be computed for the rule".format(
                rule.name
            ),
            extra={"result_key": result_key},
        )

    # Add the check details in the result
    redis.set(
        result_key,
        json.dumps(result).encode("utf-8"),
        ex=redis.seconds_until_midnight(),
    )
    logger.debug(
        "[{0}] Result added in cache ({1})".format(rule.name, result_key),
        extra={"result_key": result_key},
    )

    return result
