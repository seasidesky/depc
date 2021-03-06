from depc.extensions import cel
from depc.tasks.checks import execute_check, validate_results


@cel.task(bind=True, name="SCHEDULE_RULE", max_retries=0)
def execute_async_rule(self, rule_id, rule_checks, result_key, kwargs):
    checks = [
        execute_check(
            logger=self.logger,
            result_key=result_key,
            check_id=check_id,
            variables=kwargs.get("variables", {}),
            name=kwargs.get("name"),
            start=kwargs.get("start"),
            end=kwargs.get("end"),
        )
        for check_id in rule_checks
    ]

    # Aggregation callback
    qos = validate_results(
        logger=self.logger,
        checks=checks,
        rule_id=rule_id,
        result_key=result_key,
        context=kwargs,
    )

    return qos


def execute_sync_rule(rule_id, rule_checks, result_key, logger, kwargs):
    checks = [
        execute_check(
            logger=logger,
            result_key=result_key,
            check_id=check_id,
            variables=kwargs.get("variables", {}),
            name=kwargs.get("name"),
            start=kwargs.get("start"),
            end=kwargs.get("end"),
        )
        for check_id in rule_checks
    ]

    # Aggregation callback
    qos = validate_results(
        logger=logger,
        checks=checks,
        rule_id=rule_id,
        result_key=result_key,
        context=kwargs,
    )

    return qos
