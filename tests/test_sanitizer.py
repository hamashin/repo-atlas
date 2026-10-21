import pytest

from atlas.sanitizer import PathFilter, Sanitizer


@pytest.fixture
def sanitizer():
    return Sanitizer(internal_domains=("example.internal",), deny_terms=("nas01",))


FAKE_GH = "gh" + "p_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"
FAKE_SLACK = "xo" + "xb-" + "1234567890-abcdefghij"
FAKE_AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"


@pytest.mark.parametrize(
    "text,kind",
    [
        ("サーバーは 192.0.2.10 で動く", "ipv4"),
        ("subnet 198.51.100.0/24", "ipv4"),
        ("addr 2001:db8::1 です", "ipv6"),
        ("mac aa:bb:cc:dd:ee:ff", "mac_address"),
        ("mac AA-BB-CC-DD-EE-01", "mac_address"),
        ("連絡先 someone@example.com", "email"),
        (f"token {FAKE_GH}", "github_token"),
        (f"slack {FAKE_SLACK}", "slack_token"),
        (f"aws {FAKE_AWS}", "aws_key"),
        ("https://hooks.slack.com/services/T000/B000/XXXX", "webhook_url"),
        ("password: hunter2hunter2", "secret_assignment"),
        ("API_KEY=abcdef123456", "secret_assignment"),
        ("git clone https://user:pass@example.com/x.git", "url_credentials"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----", "private_key"),
        ("-----BEGIN RSA PRIVATE KEY-----\n途中で切れた鍵", "private_key"),
        ("nas.example.internal に保存", "internal_domain"),
        ("camera.local を見る", "local_hostname"),
        ("router.home.arpa", "local_hostname"),
        ("NAS01 に退避", "deny_term"),
        ("arn:aws:sns:ap-northeast-1:123456789012:alerts", "aws_arn"),
        ("AccountId: 123456789012", "aws_account_id"),
        ("AWS アカウント 123456789012 で運用", "aws_account_id"),
        ("key Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0LmNbVcXz12", "high_entropy"),
    ],
)
def test_detects_and_masks(sanitizer, text, kind):
    assert kind in {f.kind for f in sanitizer.scan(text, "t")}
    masked = sanitizer.mask(text)
    assert sanitizer.scan(masked, "t") == []


@pytest.mark.parametrize(
    "text",
    [
        "Python 3.12 と podman 5.7 を使う",
        "毎日 08:00 に実行する",
        "時刻 12:34:56 のログ",
        "src/atlas/sanitizer_helpers/very_long_module_name_here.py",
        "GITHUB_TOKEN= を設定する",
        "password: ${DB_PASSWORD}",
        "token=[SECRET]",
        "公開リポジトリ hamashin/repo-atlas",
        "SHA は 3f2a9c1 です",
        "バージョン 202610191552 を作成",
    ],
)
def test_keeps_harmless_text(sanitizer, text):
    assert sanitizer.scan(text, "t") == []
    assert sanitizer.mask(text) == text


def test_deny_term_is_word_bounded(sanitizer):
    assert sanitizer.scan("nas01x と xnas01", "t") == []


@pytest.mark.parametrize(
    "path,excluded",
    [
        (".env", True),
        (".env.production", True),
        ("config/.env", True),
        ("certs/server.pem", True),
        ("keys/id_ed25519", True),
        ("deploy_key_rsa", True),
        ("secrets/token.txt", True),
        ("app/secrets/db.yaml", True),
        ("infra/terraform.tfstate", True),
        ("data/state.sqlite3", True),
        (".env.sample", True),
        ("README.md", False),
        ("src/app.py", False),
        ("docs/environment.md", False),
    ],
)
def test_path_filter(path, excluded):
    assert PathFilter().is_excluded(path) is excluded


def test_path_filter_extra_globs():
    assert PathFilter(("*.csv",)).is_excluded("data/hosts.csv")
