"""Registered RPC results and event payloads, shared by validation and code generation.

Parameters continue to come from handler signatures. Records permit additive
fields, but validate every field consumed by a current client. Validation never
replaces the handler's value or fills defaults into a response.
"""
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ConfigDict, Field, create_model
from pydantic.json_schema import GenerateJsonSchema

from badshop.providers.profiles import Profile
from badshop.server.protocol import DocumentContext
from badshop.server.settings import RecentProject, Settings
from badshop.session.models import ArtifactMeta, BranchSnapshot, Message, SessionData, Step
from badshop.session.preferences import CreativePreferences
from badshop.session.recipes import Recipe
from badshop.session.library import LibraryEntry


def record(name: str, /, **fields):
    return create_model(name, __config__=ConfigDict(extra='allow', strict=True),
                        **{key: value if isinstance(value, tuple) else (value, ...)
                           for key, value in fields.items()})


TurnOutcome = record('TurnOutcome', run_id=str | None, reason=str, error=(str | None, None))
SessionSnapshot = create_model('SessionSnapshot', __base__=SessionData,
    context=(DocumentContext, ...), path=(str | None, ...), document_revision=(int, ...),
    unsaved_changes=(bool, ...), turn_running=(bool, ...), batch_running=(bool, ...),
    pending_approvals=(list[str], ...), restorable=(str | None, ...), bypass_tools=(list[str], ...),
    run_id=(str | None, ...), last_turn_outcome=(TurnOutcome | None, ...), recipes=(list[Recipe], ...),
    stream_text=(str, ...),
    manual_history=(record('ManualHistory', undo=str | None, redo=str | None), ...),
    manual_undo=(list[BranchSnapshot], Field(default_factory=list, exclude=True)),
    manual_redo=(list[BranchSnapshot], Field(default_factory=list, exclude=True)))
PathResult = record('PathResult', path=str)
ArtifactPayload = record('ArtifactPayload', meta=ArtifactMeta, mime=str, data=str)
Imported = record('ImportedArtifacts', working=ArtifactMeta, original=ArtifactMeta)
Thumbnail = record('Thumbnail', mime=str, data=str)
Branch = record('BranchSummary', id=str, name=str, created_at=float, step_count=int, preview_id=str | None)
BranchList = record('BranchList', active_id=str | None, branches=list[Branch])
Tool = record('Tool', name=str, summary=str, description=str, category=str, mutates=bool,
              network=bool, read_only=bool, writes_files=bool, cli_positionals=list[str], cli_flags=dict[str, str],
              parameter_schema=(dict, Field(alias='schema')))
Asset = record('Asset', name=str, label=str, approx_mb=float, present=bool)
SourceHealth = record('SourceHealth', status=Literal['failed', 'responded', 'not checked'],
                      results=(int, 0), step_id=(str | None, None))
SourceStatus = record('SourceStatus', id=str, name=str, configured=bool, requires_key=bool,
                      env_var=str | None, health=(SourceHealth | None, None))
Recent = record('RecentIdea', kind=str, value=str, label=(str | None, None), url=(str | None, None))
CLIDetection = record('CLIDetection', cli=Literal['claude', 'codex', 'gemini'], executable=str | None,
                      version=str | None, available=bool, supported=bool, experimental=bool, error=(str | None, None))
ProviderStatus = record('ProviderStatus', profile_id=str | None, status=str, error=(str | None, None),
                        capabilities=(dict, {}), warnings=(list[str], []), probed=(bool, False))
Diagnostics = record('Diagnostics', versions=dict[str, str], os=str, log_path=str, log_lines=list[str])
RetroStyle = record('RetroStyle', id=str, name=str, era=str, family=str, width=int, height=int, preview=str)
LayoutSlot = record('LayoutSlot', name=str, box=list[int], caption_box=list[int], mask=(str | None, None))
Layout = record('Layout', id=str, name=str, width=int, height=int, max_images=int, slots=list[LayoutSlot])
Pack = record('Pack', id=str, name=str, description=str, count=int)
MediaCandidate = record('MediaCandidate', id=str, label=str, time_s=(float | None, None), page=(int | None, None),
                        thumbnail_data_url=str, width=int, height=int)
MediaPreview = record('MediaPreview', id=str, source_name=str, kind=Literal['video', 'document'],
                      width=int, height=int, sheet_data_url=str, candidates=list[MediaCandidate], warnings=list[str])
CollectionSummary = record('CollectionSummary', id=str, name=str, count=int, duplicates=int, warnings=list[str])
CollectionEntry = record('CollectionEntry', id=str, name=str, tags=list[str], description=str,
                         thumbnail_data_url=str, width=int, height=int, duplicate_of=(str | None, None))
Credits = record('Credits', sources=list[dict], notice=str)
RecipeRow = record('RecipeRow', index=int, status=str, step_ids=list[str], output_id=str | None, error=str | None)
RecipeRun = record('RecipeRun', completed=list[str], errors=list[record('RecipeError', message=str)],
                   cancelled=bool, rows=list[RecipeRow])
RecentProjectStatus = create_model('RecentProjectStatus', __base__=RecentProject, available=(bool, ...))
SettingsResponse = create_model('SettingsResponse', __base__=Settings, saved_designs=(list[Recipe], ...))

RESULTS = {
    'projects.recent': list[RecentProjectStatus], 'projects.forget': record('ForgottenProject', forgotten=bool),
    'history.undo': SessionSnapshot, 'history.redo': SessionSnapshot,
    'session.get': SessionSnapshot, 'session.new': SessionSnapshot, 'session.open': SessionSnapshot,
    'session.restore': SessionSnapshot, 'session.set_approval_mode': SessionSnapshot,
    'session.save': PathResult, 'session.save_as': PathResult, 'session.export_recipe': PathResult,
    'branches.list': BranchList, 'branches.create': SessionSnapshot, 'branches.switch': SessionSnapshot,
    'branches.rename': BranchList, 'branches.remove': BranchList,
    'tools.list': list[Tool], 'tools.run': Step, 'tools.preview': list[str],
    'steps.edit': record('StaleSteps', stale=list[str]), 'steps.preview': list[str],
    'steps.controls': SessionSnapshot, 'steps.replay_from': list[Step], 'steps.delete': record('DeletedStep', deleted=str),
    'approval.respond': record('ApprovalResult', ok=bool),
    'artifacts.get': ArtifactPayload, 'artifacts.frame': ArtifactPayload, 'artifacts.import': Imported, 'export': PathResult,
    'providers.list': list[Profile], 'providers.save': Profile, 'providers.add': Profile,
    'providers.delete': record('DeletedProvider', deleted=bool), 'providers.select': SessionSnapshot,
    'providers.on_device': SessionSnapshot, 'providers.test': ProviderStatus, 'providers.detect': list[CLIDetection],
    'settings.get': SettingsResponse, 'settings.set': SettingsResponse, 'diagnostics.get': Diagnostics,
    'assets.status': list[Asset], 'assets.download': PathResult, 'assets.cancel': record('CancelledAsset', cancelled=bool),
    'updates.begin': record('UpdateLease', lease=str), 'updates.end': record('EndedUpdate', ended=bool),
    'chat.send': record('StartedTurn', started=bool), 'chat.retry': record('RetriedTurn', started=bool),
    'chat.stop': record('StoppedTurn', stopped=bool), 'chat.pause': record('PauseRequest', requested=bool),
    'chat.undo': SessionSnapshot, 'chat.finish_checkpoint': SessionSnapshot,
    'sources.status': list[SourceStatus], 'sources.key': record('SavedSourceKey', saved=bool),
    'novelty.recent': list[Recent], 'novelty.clear': record('ClearedNovelty', cleared=bool),
    'library.list': list[LibraryEntry], 'library.save': LibraryEntry, 'library.update': LibraryEntry,
    'library.import': record('ImportedLibrary', working=ArtifactMeta, original=ArtifactMeta, entry=LibraryEntry),
    'library.remove': record('RemovedLibraryEntry', removed=bool), 'library.thumbnail': Thumbnail,
    'retro.list': list[RetroStyle], 'creative.set': CreativePreferences,
    'recipes.capture': Recipe, 'recipes.save': Recipe, 'recipes.remove': record('RemovedRecipe', removed=bool),
    'recipes.run': RecipeRun, 'recipes.stop': record('StoppedRecipe', stopped=bool),
    'credits.get': Credits, 'credits.export': record('ExportedCredits', path=str, credits=str),
    'remix.inspect': record('RemixSummary', artifact_ids=list[str], step_count=int, sources=list[dict]),
    'remix.export': PathResult, 'layouts.list': list[Layout], 'packs.list': list[Pack],
    'packs.install': list[LibraryEntry], 'packs.export': record('ExportedPack', path=str, count=int),
    'packs.import': record('ImportedPack', entries=list[LibraryEntry], name=str, count=int),
    'media.preview': MediaPreview, 'media.status': record('MediaStatus', video=bool, pdf=bool),
    'media.cancel': record('CancelledMedia', cancelled=bool),
    'media.capture': MediaPreview | None, 'media.discard': record('DiscardedMedia', discarded=bool),
    'media.import': record('ImportedMedia', artifacts=list[ArtifactMeta], provenance=dict),
    'collections.index': CollectionSummary, 'collections.list': list[CollectionSummary],
    'collections.search': list[CollectionEntry], 'collections.update': CollectionEntry,
    'collections.import': Imported, 'collections.remove': record('RemovedCollection', removed=bool),
    'cache.status': record('CacheStatus', bytes=int, files=int, budget_mb=int),
    'cache.clear': record('ClearedCache', removed=int),
}

READ_METHODS = frozenset({
    'projects.recent',
    'session.get', 'branches.list', 'tools.list', 'artifacts.get', 'artifacts.frame', 'providers.list',
    'providers.detect', 'diagnostics.get', 'settings.get', 'assets.status', 'sources.status', 'novelty.recent',
    'library.list', 'library.thumbnail', 'retro.list', 'recipes.capture', 'credits.get', 'remix.inspect',
    'layouts.list', 'packs.list', 'media.status', 'collections.list', 'collections.search', 'cache.status',
    'steps.preview', 'tools.preview',
})
GLOBAL_METHODS = frozenset({
    'projects.recent', 'projects.forget', 'media.capture', 'media.discard',
    'tools.list', 'providers.list', 'providers.save', 'providers.add', 'providers.delete', 'providers.test',
    'providers.detect', 'diagnostics.get', 'settings.get', 'settings.set', 'updates.begin', 'updates.end',
    'assets.status', 'assets.download', 'assets.cancel', 'sources.key', 'novelty.recent', 'novelty.clear',
    'library.list', 'library.update', 'library.remove', 'library.thumbnail', 'retro.list', 'layouts.list',
    'packs.list', 'packs.install', 'packs.export', 'packs.import', 'media.preview', 'media.status', 'media.cancel',
    'collections.index', 'collections.list', 'collections.search', 'collections.update', 'collections.remove',
    'cache.status', 'cache.clear',
})
LONG_METHODS = frozenset({'tools.run', 'tools.preview', 'steps.preview', 'steps.replay_from', 'assets.download',
                          'media.preview', 'collections.index', 'recipes.run', 'session.open', 'session.save',
                          'session.save_as', 'providers.test', 'packs.import', 'packs.install'})


@dataclass(frozen=True)
class MethodContract:
    result: Any
    scope: Literal['global', 'document']
    mutates: bool
    long_running: bool


METHODS = {name: MethodContract(result, 'global' if name in GLOBAL_METHODS else 'document',
                               name not in READ_METHODS, name in LONG_METHODS) for name, result in RESULTS.items()}

StepEvent = record('StepEvent', step=Step, artifacts=(list[ArtifactMeta], []))
EVENTS = {name: StepEvent for name in ('step.proposed', 'step.started', 'step.finished', 'step.failed', 'approval.needed')}
EVENTS.update({
    'step.stale': record('StaleEvent', step_ids=list[str]),
    'step.deleted': record('DeletedStepEvent', step_id=str),
    'message.delta': record('MessageDelta', text=str, run_id=(str | None, None)),
    'message.done': record('MessageDone', message=Message, run_id=(str | None, None)),
    'turn.started': record('TurnStarted', run_id=str),
    'turn.finished': record('TurnFinished', run_id=str, reason=str, error=(str | None, None)),
    'approval.resolved': record('ApprovalResolved', step_id=str, decision=Literal['approve', 'reject', 'edit'], note=(str | None, None)),
    'asset.progress': record('AssetProgress', name=str, done=int, total=int | None),
    'provider.status': ProviderStatus,
    'provider.event': record('ProviderEvent', profile_id=str, cli=str, raw=str, parse_error=bool),
    'core.log': record('CoreLog', level=str, message=str), 'updates.cancel': record('UpdatesCancelled'),
})


class ResponseSchema(GenerateJsonSchema):
    """Persisted models load optional defaults but serialize all of their fields.

    Response-only records describe dictionaries and may deliberately omit fields.
    Keep this distinction at the wire boundary, not in the project-load schema.
    """

    def model_schema(self, schema):
        result = super().model_schema(schema)
        model = schema['cls']
        if model is SessionSnapshot or model.__module__ != __name__:
            result['required'] = list(result.get('properties', {}))
        return result
