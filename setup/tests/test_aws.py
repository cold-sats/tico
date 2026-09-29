import json

import pytest

from setup import aws
from setup.tests.fakes import FakeEC2, FakeIAM, FakeSSM, aws_clients


def plan(front_door="caddy", **kw):
    return aws.plan_aws(domain="tico.example.com", front_door=front_door, region="us-east-1", **kw)


def deployer(p, ec2, iam, ssm):
    return aws.Deployer(p, ec2, iam, ssm, "123456789012", say=lambda m: None, sleep=lambda s: None)


def test_plan_caddy_opens_80_443_with_an_elastic_ip_and_cloudflared_opens_nothing():
    c, t = plan("caddy"), plan("cloudflared")
    assert c.ports == [80, 443] and c.elastic_ip and t.ports == [] and not t.elastic_ip
    text = "\n".join(t.lines())
    assert "no inbound rules at all" in text and "hop limit 1" in text and "SSM" in text and "Estimated cost" in text


def test_default_size_is_small_and_costs_are_ordered():
    assert plan().instance_type == "t4g.small"
    assert plan(instance_type="t4g.small").monthly_usd < plan(instance_type="t4g.medium").monthly_usd


def test_plan_validates_inputs():
    with pytest.raises(ValueError):
        plan(instance_type="m5.24xlarge")
    with pytest.raises(ValueError):
        plan(os_family="windows")


def test_runner_plan_warns_about_memory_per_bot():
    p = aws.plan_aws(domain="https://t", front_door="none", region="us-east-1", instance_type="t4g.medium", role="runner", name="runner-a")
    assert p.ports == [] and any("per bot" in w for w in p.warnings)


def test_deploy_caddy_creates_tagged_locked_down_resources():
    ec2, iam, ssm, _ = aws_clients()
    d = deployer(plan("caddy"), ec2, iam, ssm)
    prep = d.prepare()
    iid, created = d.launch_or_reuse(prep, "#!/bin/bash\n")
    assert (iid, created, prep["public_ip"]) == ("i-1", True, "203.0.113.9")
    (run,) = ec2.called("run_instances")
    assert run["MetadataOptions"] == {"HttpTokens": "required", "HttpPutResponseHopLimit": 1, "HttpEndpoint": "enabled"}
    assert run["BlockDeviceMappings"][0]["Ebs"]["Encrypted"] and run["InstanceType"] == "t4g.small"
    assert {"Key": "ManagedBy", "Value": "tico-setup"} in run["TagSpecifications"][0]["Tags"]
    assert {"Key": "tico-setup-name", "Value": "tico-example-com"} in run["TagSpecifications"][0]["Tags"]
    assert "KeyName" not in run  # SSM, not SSH
    (ing,) = ec2.called("authorize_security_group_ingress")
    ports = {p["FromPort"] for p in ing["IpPermissions"]}
    assert ports == {80, 443} and 22 not in ports
    assert ec2.called("associate_address")[0]["InstanceId"] == "i-1"
    assert json.loads(iam.called("put_role_policy")[0]["PolicyDocument"])["Statement"][0]["Resource"].endswith(":parameter/tico/tico-example-com/env")


def test_deploy_cloudflared_has_no_ingress_and_no_eip():
    ec2, iam, ssm, _ = aws_clients()
    d = deployer(plan("cloudflared"), ec2, iam, ssm)
    prep = d.prepare()
    d.launch_or_reuse(prep, "x")
    assert not ec2.called("authorize_security_group_ingress") and not ec2.called("allocate_address")
    assert not ec2.called("associate_address")


def test_second_run_reuses_the_instance_and_sg_and_eip():
    ec2, iam, ssm, _ = aws_clients()
    d = deployer(plan("caddy"), ec2, iam, ssm)
    d.launch_or_reuse(d.prepare(), "x")
    d2 = deployer(plan("caddy"), ec2, iam, ssm)
    iid, created = d2.launch_or_reuse(d2.prepare(), "x")
    assert not created and len(ec2.called("run_instances")) == 1
    assert len(ec2.called("create_security_group")) == 1 and len(ec2.called("allocate_address")) == 1


def test_env_goes_to_a_secure_string_parameter_and_never_into_user_data():
    ec2, iam, ssm, _ = aws_clients()
    d = deployer(plan("caddy"), ec2, iam, ssm)
    d.put_env("TICO_OIDC_CLIENT_SECRET=topsecret\n")
    assert ssm.called("put_parameter")[0]["Type"] == "SecureString"
    d.launch_or_reuse(d.prepare(), "#!/bin/bash\naws ssm get-parameter\n")
    assert "topsecret" not in ec2.called("run_instances")[0]["UserData"]


def test_instance_profile_race_is_retried():
    ec2, iam, ssm, _ = aws_clients()
    real, n = ec2.run_instances, [0]

    def flaky(**kw):
        n[0] += 1
        if n[0] < 3:
            raise RuntimeError("InvalidParameterValue: Invalid IAM Instance Profile name")
        return real(**kw)

    ec2.run_instances = flaky
    d = deployer(plan("caddy"), ec2, iam, ssm)
    assert d.launch("x", "tico-x", "sg-1") == "i-1" and n[0] == 3


OURS = [{"Key": "ManagedBy", "Value": "tico-setup"}, {"Key": "tico-setup-name", "Value": "tico-example-com"}]


def test_is_ours_needs_both_tags_with_exact_values():
    assert aws.is_ours(OURS, "tico-example-com")
    assert not aws.is_ours(OURS, "other")
    assert not aws.is_ours(OURS[:1], "tico-example-com")
    assert not aws.is_ours([{"Key": "tico-setup-name", "Value": "tico-example-com"}], "tico-example-com")
    assert not aws.is_ours(None, "x")
    assert not aws.is_ours([{"Key": "ManagedBy", "Value": "terraform"}, OURS[1]], "tico-example-com")


def test_discover_and_destroy_touch_only_tagged_resources():
    stranger = {"InstanceId": "i-other", "Tags": [{"Key": "tico-setup-name", "Value": "tico-example-com"}]}
    mine = {"InstanceId": "i-mine", "Tags": OURS}
    ec2 = FakeEC2(extra_instances=[stranger, mine], extra_sgs=[{"GroupId": "sg-other", "Tags": []}, {"GroupId": "sg-mine", "Tags": OURS}])
    ec2.eips = [{"AllocationId": "eip-mine", "Tags": OURS}, {"AllocationId": "eip-other", "Tags": []}]
    iam, ssm = FakeIAM(role_tags=OURS), FakeSSM(param_tags=OURS)
    found = aws.discover(ec2, iam, ssm, "tico-example-com")
    assert found == {"instance": ["i-mine"], "elastic-ip": ["eip-mine"], "security-group": ["sg-mine"],
                     "iam-role": ["tico-tico-example-com"], "ssm-parameter": ["/tico/tico-example-com/env"]}
    aws.destroy(ec2, iam, ssm, found, say=lambda m: None, sleep=lambda s: None)
    assert ec2.called("terminate_instances") == [{"InstanceIds": ["i-mine"]}]
    assert ec2.called("release_address") == [{"AllocationId": "eip-mine"}]
    assert ec2.called("delete_security_group") == [{"GroupId": "sg-mine"}]
    assert ssm.called("delete_parameter") == [{"Name": "/tico/tico-example-com/env"}]
    assert iam.called("delete_role") == [{"RoleName": "tico-tico-example-com"}]


def test_discover_ignores_an_untagged_role_of_the_same_name():
    found = aws.discover(FakeEC2(), FakeIAM(role_tags=[]), FakeSSM(), "tico-example-com")
    assert found == {}


def test_existing_untagged_role_is_never_reused():
    iam = FakeIAM(role_tags=[])
    iam.create_role = lambda **kw: (_ for _ in ()).throw(iam.exceptions.EntityAlreadyExistsException())
    d = deployer(plan(), FakeEC2(), iam, FakeSSM())
    with pytest.raises(SystemExit, match="refusing to reuse"):
        d.ensure_role()


NAT = {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "nat-1"}
IGW = {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-1"}


def test_server_goes_in_a_subnet_routed_to_an_internet_gateway():
    ec2, iam, ssm, _ = aws_clients()
    ec2.subnets = [{"SubnetId": "subnet-priv", "DefaultForAz": True}, {"SubnetId": "subnet-pub"}]
    ec2.route_tables = [{"Associations": [{"Main": True}], "Routes": [NAT]},
                        {"Associations": [{"SubnetId": "subnet-pub"}], "Routes": [IGW]}]
    d = deployer(plan("caddy"), ec2, iam, ssm)
    d.launch_or_reuse(d.prepare(), "x")
    assert ec2.called("run_instances")[0]["SubnetId"] == "subnet-pub"


def test_subnet_without_its_own_route_table_uses_the_main_one():
    ec2, iam, ssm, _ = aws_clients()
    ec2.subnets = [{"SubnetId": "subnet-a"}]
    ec2.route_tables = [{"Associations": [{"Main": True}], "Routes": [IGW]}]
    assert deployer(plan("caddy"), ec2, iam, ssm).public_subnet() == "subnet-a"


def test_no_public_subnet_is_a_clear_error_before_anything_launches():
    ec2, iam, ssm, _ = aws_clients()
    ec2.route_tables = [{"Associations": [{"Main": True}], "Routes": [NAT]}]
    with pytest.raises(SystemExit) as e:
        deployer(plan("caddy"), ec2, iam, ssm).prepare()
    assert "internet gateway" in str(e.value) and not ec2.called("run_instances")


def test_tunnel_and_runner_need_no_public_subnet():
    ec2, iam, ssm, _ = aws_clients()
    ec2.route_tables = [{"Associations": [{"Main": True}], "Routes": [NAT]}]
    d = deployer(plan("cloudflared"), ec2, iam, ssm)
    d.launch_or_reuse(d.prepare(), "x")
    assert "SubnetId" not in ec2.called("run_instances")[0]
