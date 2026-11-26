import subprocess, sys, os
from orders_desk import runner


def test_placement_refuses_without_external_output_dir(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORDERS_AUTOMATION")}
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    r = subprocess.run([sys.executable, "-m", "orders_desk", "--worker", "place", "--workbook", "x", "--market", "WACO",
                        "--mode", "verify", "--logins", "x", "--login-market", "WACO"],
                       capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 2 and "refusing" in r.stdout


def test_bundled_browser_env_only_when_frozen_and_present(tmp_path, monkeypatch):
    assert runner.bundled_browser_env() == {}                      # source run: normal Playwright cache
    d = tmp_path / "playwright" / "driver" / "package" / ".local-browsers" / "chromium-1"
    d.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert runner.bundled_browser_env() == {"PLAYWRIGHT_BROWSERS_PATH": "0"}
