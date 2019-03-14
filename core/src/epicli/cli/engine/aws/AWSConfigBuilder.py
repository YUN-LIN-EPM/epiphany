from cli.engine.InfrastructureConfigBuilder import InfrastructureConfigBuilder
from cli.helpers.list_helpers import select_first
import cli.models.data_file_consts as model_constants
from cli.helpers.defaults_loader import load_file_from_defaults
from cli.helpers.config_merger import merge_with_defaults


class AWSConfigBuilder(InfrastructureConfigBuilder):
    def build(self, cluster_model, user_input):
        result = list()
        vpc_config = self.get_vpc_config(cluster_model, user_input)
        result.append(vpc_config)

        internet_gateway = self.get_internet_gateway(cluster_model, user_input, vpc_config)
        result.append(internet_gateway)
        route_table = self.get_routing_table(cluster_model, user_input, vpc_config, internet_gateway)
        result.append(route_table)

        result += self.get_autoscaling_groups_configs(cluster_model, user_input, vpc_config, route_table)

        return result

    def get_vpc_config(self, cluster_model, user_input):
        vpc_config = self.get_config_or_default(user_input, 'infrastructure/vpc')
        vpc_config["specification"]["address_pool"] = cluster_model["specification"]["cloud"]["vnet_address_pool"]
        vpc_config["specification"]["name"] = cluster_model["specification"]["cloud"]["cluster_name"].lower()+'vpc'
        return vpc_config

    def get_autoscaling_groups_configs(self, cluster_model, user_input, vpc_config, route_table):
        result = list()

        subnet_index = 0
        for component_key, component_value in cluster_model["specification"]["components"].items():
            if component_value["count"] < 1:
                continue
            subnet = select_first(result, lambda item: item[model_constants.KIND] == 'infrastructure/subnet' and item["specification"]["cidr_block"] == component_value["subnet_address_pool"])
            security_group = select_first(result, lambda item: item[model_constants.KIND] == 'infrastructure/security-group' and item["specification"]["cidr_block"] == component_value["subnet_address_pool"])

            if subnet is None:
                subnet = self.get_config_or_default(user_input, 'infrastructure/subnet')
                subnet["specification"]["vpc_name"] = vpc_config["specification"]["name"]
                subnet["specification"]["cidr_block"] = component_value["subnet_address_pool"]
                subnet["specification"]["name"] = 'aws-subnet-'+cluster_model["specification"]["cloud"]["cluster_name"].lower()+'-'+str(subnet_index)
                result.append(subnet)

                security_group = self.get_config_or_default(user_input, 'infrastructure/security-group')
                security_group["specification"]["name"] = 'aws-security-group-'+cluster_model["specification"]["cloud"]["cluster_name"].lower()+'-'+str(subnet_index)
                security_group["specification"]["vpc_name"] = vpc_config["specification"]["name"]
                security_group["specification"]["cidr_block"] = subnet["specification"]["cidr_block"]
                result.append(security_group)

                route_table_association = self.get_route_table_association(cluster_model, user_input, route_table, subnet, subnet_index)
                result.append(route_table_association)

                subnet_index += 1

            autoscaling_group = self.get_virtual_machine(component_value, cluster_model, user_input)
            autoscaling_group["specification"]["name"] = 'aws-asg-'+cluster_model["specification"]["cloud"]["cluster_name"].lower()+component_key
            autoscaling_group["specification"]["count"] = component_value["count"]
            autoscaling_group["specification"]["subnet"] = subnet["specification"]["name"]
            autoscaling_group["specification"]["tags"].append({'feature': component_key})

            security_group["specification"]["rules"] += autoscaling_group["specification"]["security"]["rules"]

            launch_configuration = self.get_config_or_default(user_input, 'infrastructure/launch-configuration')
            launch_configuration["specification"]["name"] = 'aws-launch-config-'+cluster_model["specification"]["cloud"]["cluster_name"].lower() + component_key
            launch_configuration["specification"]["image_id"] = autoscaling_group["specification"]["image_id"]
            launch_configuration["specification"]["size"] = autoscaling_group["specification"]["size"]
            launch_configuration["specification"]["security_groups"] = [security_group["specification"]["name"]]

            result.append(autoscaling_group)
            result.append(launch_configuration)

        return result

    def get_route_table_association(self, cluster_model, user_input, route_table, subnet, subnet_index):
        route_table_association = self.get_config_or_default(user_input, 'infrastructure/route-table-association')
        route_table_association["specification"]["name"] = 'aws-route-association-' + \
                                                           cluster_model["specification"]["cloud"][
                                                               "cluster_name"].lower() + '-' + str(subnet_index)
        route_table_association["specification"]["subnet_name"] = subnet["specification"]["name"]
        route_table_association["specification"]["route_table_name"] = route_table["specification"]["name"]
        return route_table_association

    def get_internet_gateway(self, cluster_model, user_input, vpc_config):
        internet_gateway = self.get_config_or_default(user_input, 'infrastructure/internet-gateway')
        internet_gateway["specification"]["name"] = 'aws-internet-gateway-' + cluster_model["specification"]["cloud"]["cluster_name"].lower()
        internet_gateway["specification"]["vpc_name"] = vpc_config["specification"]["name"]
        return internet_gateway

    def get_routing_table(self, cluster_model, user_input, vpc_config, internet_gateway):
        route_table = self.get_config_or_default(user_input, 'infrastructure/route-table')
        route_table["specification"]["name"] = 'aws-route-table-' + cluster_model["specification"]["cloud"]["cluster_name"].lower()
        route_table["specification"]["vpc_name"] = vpc_config["specification"]["name"]
        route_table["specification"]["route"]["gateway_name"] = internet_gateway["specification"]["name"]

        return route_table

    @staticmethod
    def get_config_or_default(user_input, kind):
        config = select_first(user_input, lambda x: x[model_constants.KIND] == kind)
        if config is None:
            return load_file_from_defaults('aws', kind)

    @staticmethod
    def get_virtual_machine(component_value, cluster_model, user_input):
        machine_selector = component_value["machine"]
        model_with_defaults = select_first(user_input, lambda x: x[model_constants.KIND] == 'infrastructure/virtual-machine' and x[model_constants.NAME] == machine_selector)
        if model_with_defaults is None:
            model_with_defaults = merge_with_defaults(cluster_model[model_constants.PROVIDER], 'infrastructure/virtual-machine', machine_selector)

        return model_with_defaults

