"""``receipts provision`` : ouvrir la frontière de reçus, hors ligne, sans campagne.

Pourquoi cette suite existe
---------------------------
Le secret de signature était jusqu'ici créé **au premier besoin réseau** :
``ensure_receipt_secret()`` n'est atteint que depuis un chemin qui s'apprête à signer un
reçu, et ``status`` refuse délibérément de créer quoi que ce soit en se contentant de
regarder. La première commande qui ouvrait donc la frontière était ``discover`` — un
appel fournisseur. Provisionner *avant* d'ouvrir la moindre socket n'était pas
exécutable : il n'existait aucune commande pour le faire.

``receipts provision`` comble exactement ce trou, et rien de plus. Elle ne réimplémente
ni la génération ni la publication : elle appelle ``ensure_receipt_secret()``, donc la
même publication atomique « octets d'abord, nom ensuite » qui existe précisément pour
qu'une interruption ne laisse jamais un nom qui existe et qui est vide.

Ce que cette suite épingle, et qui est le point
-----------------------------------------------
Une commande qui crée un secret est une commande qui peut le détruire. Les gardes les
plus importantes ici sont donc négatives : un secret existant n'est **jamais** remplacé,
même invalide, parce que le réécrire transformerait en bruit tout reçu déjà signé avec
lui. Et rien de ce que la commande affiche ne doit permettre de reconstituer la clé —
ni sa valeur, ni sa longueur, ni un préfixe, ni une empreinte.

Tout est synthétique. Aucune valeur réelle d'environnement n'est lue ni affichée, aucune
socket n'est ouverte, aucun crédit n'est engagé, et le chemin de production
``~/.local/state/betmaxxing/activation-receipts`` n'est jamais touché.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import receipt_store

VARIABLE = "BETMAXXING_ACTIVATION_RECEIPTS"
SECRET_VARIABLE = receipt_store.SECRET_ENVIRONMENT_VARIABLE

#: Les noms des variables de clé fournisseur. Cette suite les purge **par leur nom** et
#: ne lit jamais leur valeur : une suite qui inspecte un secret réel pour vérifier
#: qu'elle ne l'utilise pas l'a déjà lu.
PROVIDER_KEY_VARIABLES = (
    "BETMAXXING_THE_ODDS_API_KEY",
    "BETMAXXING_ODDS_API_KEY",
    "THE_ODDS_API_KEY",
)

#: Un secret synthétique valide : 64 hexadécimaux minuscules, reconnaissable, et
#: délibérément pas une forme en usage.
SYNTHETIC_SECRET = "abcdef0123456789" * 4

runner = CliRunner()


@pytest.fixture(autouse=True)
def _boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Une frontière neuve par test, jamais celle du répertoire courant.

    Le répertoire n'est **pas** créé : une installation vierge est exactement l'état
    que la commande doit savoir ouvrir, et plusieurs tests assertent dessus.
    """
    directory = tmp_path / "boundary" / "activation-receipts"
    monkeypatch.setenv(VARIABLE, str(directory))
    monkeypatch.delenv(SECRET_VARIABLE, raising=False)
    for name in PROVIDER_KEY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return directory


def provision(*arguments: str) -> Result:
    return runner.invoke(act.app, ["receipts", "provision", *arguments])


def secret_path(directory: Path) -> Path:
    return directory / act.SECRET_FILENAME


def read_status() -> dict[str, object]:
    done = runner.invoke(act.app, ["status", "--json"])
    assert done.exit_code == 0, done.output
    return json.loads(done.output)


# ---------------------------------------------------------------------------
# Le chemin heureux, et son idempotence
# ---------------------------------------------------------------------------
class TestItOpensTheBoundary:
    def test_an_absent_directory_is_provisioned(self, _boundary: Path) -> None:
        assert not _boundary.exists()
        done = provision()
        assert done.exit_code == 0, done.output
        assert secret_path(_boundary).is_file()

    def test_an_existing_directory_without_a_secret_is_provisioned(self, _boundary: Path) -> None:
        _boundary.mkdir(parents=True)
        os.chmod(_boundary, 0o700)
        done = provision()
        assert done.exit_code == 0, done.output
        assert secret_path(_boundary).is_file()

    def test_the_secret_is_sixty_four_lowercase_hexadecimals(self, _boundary: Path) -> None:
        assert provision().exit_code == 0
        text = secret_path(_boundary).read_text(encoding="utf-8")
        assert re.fullmatch(r"[0-9a-f]{64}", text.strip()), "forme du secret"
        assert len(text.strip()) == receipt_store.SECRET_HEX_LENGTH

    def test_the_permissions_are_0700_and_0600(self, _boundary: Path) -> None:
        assert provision().exit_code == 0
        assert stat.S_IMODE(_boundary.stat().st_mode) == 0o700
        assert stat.S_IMODE(secret_path(_boundary).stat().st_mode) == 0o600

    def test_the_owner_is_the_current_account(self, _boundary: Path) -> None:
        assert provision().exit_code == 0
        assert secret_path(_boundary).stat().st_uid == os.getuid()
        assert _boundary.stat().st_uid == os.getuid()

    def test_a_second_run_keeps_the_very_same_secret(self, _boundary: Path) -> None:
        """Idempotence, et donc absence de rotation. La garde la plus importante ici."""
        assert provision().exit_code == 0
        first = secret_path(_boundary).read_bytes()
        stamp = secret_path(_boundary).stat().st_mtime_ns

        done = provision()
        assert done.exit_code == 0, done.output
        assert secret_path(_boundary).read_bytes() == first, "le secret a été remplacé"
        assert secret_path(_boundary).stat().st_mtime_ns == stamp, "le fichier a été réécrit"


# ---------------------------------------------------------------------------
# Deux processus, une seule clé
# ---------------------------------------------------------------------------
class TestOnlyOneKeySurvivesARace:
    @pytest.mark.slow
    def test_concurrent_provisioning_leaves_one_valid_secret(self, _boundary: Path) -> None:
        """Deux processus réels, lancés ensemble, sur la même frontière neuve.

        In-process, deux appels seraient sérialisés par le GIL et ne prouveraient rien
        de la publication atomique. Ce qui est vérifié ici est ce que ``publish_bytes``
        garantit : le perdant lit la valeur du gagnant, et les deux repartent avec la
        même clé complète et valide.
        """
        environment = {**os.environ, VARIABLE: str(_boundary), "NO_COLOR": "1"}
        environment.pop("FORCE_COLOR", None)
        environment.pop(SECRET_VARIABLE, None)
        for name in PROVIDER_KEY_VARIABLES:
            environment.pop(name, None)
        environment["PYTHONPATH"] = str(Path(act.__file__).resolve().parents[4] / "src")

        command = [
            sys.executable,
            "-m",
            "betmaxxing.providers.the_odds_api.activation",
            "receipts",
            "provision",
            "--json",
        ]
        children = [
            subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment
            )
            for _ in range(2)
        ]
        results = [child.communicate() for child in children]

        for (out, err), child in zip(results, children, strict=True):
            assert child.returncode == 0, out + err
        text = secret_path(_boundary).read_text(encoding="utf-8").strip()
        assert re.fullmatch(r"[0-9a-f]{64}", text)
        # Exactement un fichier de secret, et rien d'autre.
        assert sorted(p.name for p in _boundary.iterdir()) == [act.SECRET_FILENAME]
        # Les deux repartent avec la même frontière ouverte, pas deux clés.
        for out, _ in results:
            assert json.loads(out)["boundary_state"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Ce que la commande refuse
# ---------------------------------------------------------------------------
class TestItRefusesAnUnsafeBoundary:
    def test_an_unset_variable_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Le défaut relatif reste le défaut, et provisionner ne s'y applique pas.

        ``DEFAULT_RECEIPT_DIR`` se résout contre le répertoire courant. Créer une clé
        durable là où l'opérateur se trouve à cet instant est un piège, pas un défaut
        raisonnable : la frontière doit être nommée explicitement.
        """
        monkeypatch.delenv(VARIABLE, raising=False)
        done = provision()
        assert done.exit_code == 1
        assert VARIABLE in done.output

    def test_an_empty_variable_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(VARIABLE, "   ")
        assert provision().exit_code == 1

    def test_a_relative_path_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(VARIABLE, "activation-receipts")
        done = provision()
        assert done.exit_code == 1
        assert not (tmp_path / "activation-receipts").exists(), "rien ne doit être créé"

    def test_the_relative_default_spelled_out_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(VARIABLE, act.DEFAULT_RECEIPT_DIR)
        assert provision().exit_code == 1
        assert not (tmp_path / act.DEFAULT_RECEIPT_DIR).exists()

    def test_a_symlinked_boundary_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        monkeypatch.setenv(VARIABLE, str(link))
        done = provision()
        assert done.exit_code == 1
        assert not secret_path(real).exists(), "aucun secret derrière le lien"

    def test_a_regular_file_in_place_of_the_directory_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        occupied = tmp_path / "occupied"
        occupied.write_text("pas un répertoire", encoding="utf-8")
        monkeypatch.setenv(VARIABLE, str(occupied))
        assert provision().exit_code == 1
        assert occupied.read_text(encoding="utf-8") == "pas un répertoire"

    def test_a_fifo_in_place_of_the_directory_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        monkeypatch.setenv(VARIABLE, str(fifo))
        assert provision().exit_code == 1


class TestItNeverRepairsAnInvalidSecret:
    """Remplacer un secret invalide rendrait invérifiable tout reçu déjà signé avec lui.

    Chaque cas assert donc **deux** choses : le refus, et l'intégrité octet pour octet
    de ce qui était sur le disque.
    """

    @pytest.mark.parametrize(
        ("label", "content"),
        [
            ("vide", ""),
            ("tronqué", "abcdef0123456789"),
            ("non hexadécimal", "z" * 64),
            ("majuscules", "ABCDEF0123456789" * 4),
            ("trop long", "a" * 65),
            ("espaces internes", "abcdef 123456789" * 4),
        ],
    )
    def test_an_invalid_secret_is_refused_and_left_untouched(
        self, _boundary: Path, label: str, content: str
    ) -> None:
        _boundary.mkdir(parents=True)
        os.chmod(_boundary, 0o700)
        target = secret_path(_boundary)
        target.write_text(content, encoding="utf-8")
        os.chmod(target, 0o600)

        done = provision()
        assert done.exit_code == 1, f"{label} aurait dû être refusé"
        assert target.read_text(encoding="utf-8") == content, f"{label} a été réécrit"

    def test_a_world_readable_secret_is_refused_and_not_corrected(self, _boundary: Path) -> None:
        _boundary.mkdir(parents=True)
        os.chmod(_boundary, 0o700)
        target = secret_path(_boundary)
        target.write_text(SYNTHETIC_SECRET, encoding="utf-8")
        os.chmod(target, 0o644)

        done = provision()
        assert done.exit_code == 1
        assert stat.S_IMODE(target.stat().st_mode) == 0o644, "les droits ont été « réparés »"
        assert target.read_text(encoding="utf-8") == SYNTHETIC_SECRET

    def test_a_directory_named_like_the_secret_is_refused(self, _boundary: Path) -> None:
        _boundary.mkdir(parents=True)
        os.chmod(_boundary, 0o700)
        secret_path(_boundary).mkdir()
        assert provision().exit_code == 1
        assert secret_path(_boundary).is_dir()


class TestAStorageFaultLeavesNothingPartial:
    def test_a_publication_fault_is_typed_and_leaves_no_secret(
        self, _boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Une panne d'écriture ne doit pas laisser un nom qui existe et qui est vide."""
        broken = {"on": True}
        real = receipt_store.SecureDirectory.publish_bytes

        def failing(
            self: receipt_store.SecureDirectory, name: str, payload: bytes
        ) -> receipt_store.Published:
            if broken["on"] and name == act.SECRET_FILENAME:
                raise receipt_store.PersistenceFailed("panne de publication simulée")
            return real(self, name, payload)

        monkeypatch.setattr(receipt_store.SecureDirectory, "publish_bytes", failing)
        done = provision()
        assert done.exit_code == 1
        assert not secret_path(_boundary).exists(), "un secret partiel a été laissé"

        broken["on"] = False
        assert provision().exit_code == 0
        assert secret_path(_boundary).is_file()

    def test_a_sync_fault_is_typed(self, _boundary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing(self: receipt_store.SecureDirectory) -> None:
            raise receipt_store.PersistenceFailed("panne de synchronisation simulée")

        monkeypatch.setattr(receipt_store.SecureDirectory, "fsync", failing)
        done = provision()
        assert done.exit_code == 1
        # Le vocabulaire de refus du harnais, pas un message libre : une panne de
        # stockage sort par le même statut typé que tout autre refus d'étape.
        assert str(act.ActivationStatus.PREPARED_NOT_EXECUTED) in done.output

        # Ce qui reste sur le disque n'est jamais *partiel*. La synchronisation du
        # répertoire échoue après le renommage : les octets ont été écrits et
        # synchronisés avant, donc le nom peut exister avec un contenu complet dont
        # seule la durabilité n'est pas prouvée. La commande refuse alors — et surtout
        # elle ne supprime pas ce qu'elle vient d'écrire, parce qu'une clé complète
        # effacée est exactement la perte que tout le reste du module empêche.
        if secret_path(_boundary).exists():
            text = secret_path(_boundary).read_text(encoding="utf-8").strip()
            assert re.fullmatch(r"[0-9a-f]{64}", text), "un secret partiel a été laissé"

    def test_a_retry_after_a_sync_fault_keeps_that_same_key(
        self, _boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La reprise est sûre : elle relit la clé, elle n'en fabrique pas une seconde."""
        broken = {"on": True}
        real = receipt_store.SecureDirectory.fsync

        def failing(self: receipt_store.SecureDirectory) -> None:
            if broken["on"]:
                raise receipt_store.PersistenceFailed("panne de synchronisation simulée")
            return real(self)

        monkeypatch.setattr(receipt_store.SecureDirectory, "fsync", failing)
        assert provision().exit_code == 1
        left = secret_path(_boundary).read_bytes() if secret_path(_boundary).exists() else None

        broken["on"] = False
        done = provision()
        assert done.exit_code == 0, done.output
        after = secret_path(_boundary).read_bytes()
        assert re.fullmatch(rb"[0-9a-f]{64}", after.strip())
        if left is not None:
            assert after == left, "la reprise a fabriqué une seconde clé"


# ---------------------------------------------------------------------------
# Rien de ce qui sort ne révèle la clé
# ---------------------------------------------------------------------------
class TestItNeverRevealsTheSecret:
    def _outputs(self, _boundary: Path) -> tuple[str, str, str]:
        human = provision()
        assert human.exit_code == 0, human.output
        machine = provision("--json")
        assert machine.exit_code == 0, machine.output
        text = secret_path(_boundary).read_text(encoding="utf-8").strip()
        return human.output, machine.output, text

    def test_neither_output_contains_the_secret(self, _boundary: Path) -> None:
        human, machine, text = self._outputs(_boundary)
        assert text not in human
        assert text not in machine

    def test_neither_output_contains_a_prefix_or_a_suffix(self, _boundary: Path) -> None:
        human, machine, text = self._outputs(_boundary)
        for fragment in (text[:8], text[-8:], text[:16], text[-16:]):
            assert fragment not in human, "préfixe ou suffixe publié"
            assert fragment not in machine, "préfixe ou suffixe publié"

    def test_neither_output_publishes_a_length_or_a_digest(self, _boundary: Path) -> None:
        human, machine, _ = self._outputs(_boundary)
        payload = json.loads(machine)
        assert set(payload) <= {
            "status",
            "boundary_state",
            "boundary_reason",
            "unresolved_attempt_intents",
        }, payload
        for rendered in (human, machine):
            assert "64" not in rendered, "la longueur du secret est publiée"
        # Aucune chaîne longue d'hexadécimaux nulle part.
        assert not re.search(r"\b[0-9a-f]{16,}\b", human)
        assert not re.search(r"\b[0-9a-f]{16,}\b", machine)

    def test_the_json_output_carries_no_ansi_escape(self, _boundary: Path) -> None:
        done = provision("--json")
        assert done.exit_code == 0
        assert "\x1b[" not in done.output
        json.loads(done.output)

    def test_a_refusal_never_names_the_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le vocabulaire des refus est fermé ; un chemin choisi ailleurs n'y entre pas."""
        secretive = tmp_path / "un-nom-que-personne-ne-doit-lire"
        secretive.write_text("occupé", encoding="utf-8")
        monkeypatch.setenv(VARIABLE, str(secretive))
        done = provision()
        assert done.exit_code == 1
        assert "un-nom-que-personne-ne-doit-lire" not in done.output


# ---------------------------------------------------------------------------
# La variable d'environnement garde la politique existante
# ---------------------------------------------------------------------------
class TestTheInjectedSecretKeepsItsPolicy:
    def test_a_valid_variable_writes_no_file(
        self, _boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Une variable valide *est* la configuration : rien n'est écrit sur le disque."""
        monkeypatch.setenv(SECRET_VARIABLE, SYNTHETIC_SECRET)
        done = provision()
        assert done.exit_code == 0, done.output
        assert not secret_path(_boundary).exists(), "un fichier a doublé la variable"

    def test_a_valid_variable_still_opens_the_boundary(
        self, _boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La variable fournit la clé ; le répertoire reste nécessaire aux reçus."""
        monkeypatch.setenv(SECRET_VARIABLE, SYNTHETIC_SECRET)
        done = provision("--json")
        assert done.exit_code == 0, done.output
        assert json.loads(done.output)["boundary_state"] == "AVAILABLE"

    @pytest.mark.parametrize("value", ["", "   ", "zz", "ABC123", "a" * 63])
    def test_an_invalid_variable_fails_closed_without_touching_the_file(
        self, _boundary: Path, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """Présente mais invalide = échec fermé, jamais un repli sur le fichier."""
        monkeypatch.setenv(SECRET_VARIABLE, value)
        done = provision()
        assert done.exit_code == 1
        assert not secret_path(_boundary).exists(), "repli sur le fichier"

    def test_an_invalid_variable_never_echoes_its_value(
        self, _boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(SECRET_VARIABLE, "ZZTOPSECRET" * 6)
        done = provision()
        assert done.exit_code == 1
        assert "ZZTOPSECRET" not in done.output


# ---------------------------------------------------------------------------
# Ce que la commande ne fait pas
# ---------------------------------------------------------------------------
class TestItEngagesNothing:
    def test_it_creates_no_receipt_and_no_intent(self, _boundary: Path) -> None:
        assert provision().exit_code == 0
        names = sorted(p.name for p in _boundary.iterdir())
        assert names == [act.SECRET_FILENAME], names
        assert not [n for n in names if n.endswith(".json") or n.endswith(".intent")]

    def test_it_reads_no_provider_key(
        self, _boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Chaque nom de variable fournisseur est instrumenté, sans valeur réelle."""
        touched: list[str] = []
        real_get = os.environ.get

        def watching(key: str, default: object = None) -> object:
            if key in PROVIDER_KEY_VARIABLES:
                touched.append(key)
            return real_get(key, default)

        monkeypatch.setattr(os.environ, "get", watching)
        assert provision().exit_code == 0
        assert touched == [], touched

    def test_it_opens_no_socket(self, _boundary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """La session bloque déjà le réseau ; ici toute *tentative* rend le test rouge."""
        import socket

        attempts: list[object] = []

        def refusing(self: socket.socket, address: object) -> None:
            attempts.append(address)
            raise AssertionError(f"tentative de connexion vers {address!r}")

        monkeypatch.setattr(socket.socket, "connect", refusing)
        monkeypatch.setattr(socket.socket, "connect_ex", refusing)
        assert provision().exit_code == 0
        assert attempts == []

    def test_it_accounts_no_credit(self, _boundary: Path) -> None:
        assert provision().exit_code == 0
        payload = read_status()
        assert payload["accounted_credits_total"] == 0
        assert payload["verified_receipts"] == 0


# ---------------------------------------------------------------------------
# Ce que `status` publie ensuite — le critère d'acceptation, littéralement
# ---------------------------------------------------------------------------
class TestStatusThenPublishesAnOpenBoundary:
    def test_status_creates_nothing_on_an_absent_boundary(self, _boundary: Path) -> None:
        """`status` reste strictement en lecture seule : provisionner est le seul verbe."""
        payload = read_status()
        assert payload["receipt_boundary_state"] == "ABSENT"
        assert not _boundary.exists(), "status a créé la frontière"

    def test_the_three_published_fields_after_provisioning(self, _boundary: Path) -> None:
        assert provision().exit_code == 0
        payload = read_status()
        assert payload["receipt_boundary_state"] == "AVAILABLE"
        assert payload["receipt_boundary_reason"] == ""
        assert payload["unresolved_attempt_intents"] == 0

    def test_the_command_reports_the_same_three_fields(self, _boundary: Path) -> None:
        """La commande n'affirme le succès qu'après avoir relu la frontière."""
        done = provision("--json")
        assert done.exit_code == 0, done.output
        payload = json.loads(done.output)
        assert payload["boundary_state"] == "AVAILABLE"
        assert payload["boundary_reason"] == ""
        assert payload["unresolved_attempt_intents"] == 0

    def test_provisioning_does_not_promote_the_adapter(self, _boundary: Path) -> None:
        assert provision().exit_code == 0
        payload = read_status()
        assert payload["adapter_state"] == "IMPLEMENTED_UNVERIFIED"
