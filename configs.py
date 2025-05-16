from pydantic_settings import BaseSettings


class Configs(BaseSettings):
    secret_key: str
    mongodb: str
    mongodb_uri: str

    algorithm: str
    exp_time: int

    stripe_api_key: str

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str

    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'


def get_configs():
    return Configs()
