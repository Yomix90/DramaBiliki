import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show appFlavor;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:ota_update/ota_update.dart';
import 'package:url_launcher/url_launcher.dart';
import '../models/account.dart';
import '../providers/app_providers.dart';
import 'app_theme.dart';
import 'constants.dart';
import 'localization.dart';
import 'server_url.dart';

/// Asks the bridge whether a newer APK is published, then downloads it inside the
/// app and opens the Android installer (the user only confirms "Install").
/// A forced update cannot be dismissed.
Future<void> checkForAppUpdate(BuildContext context, WidgetRef ref) async {
  // Store builds are updated by the store itself (Amazon forbids self-updates).
  if (appFlavor == 'amazon') return;
  try {
    final info = await ref.read(repositoryProvider).checkVersion(AppConstants.appVersion);
    if (!info.hasUpdate || info.downloadUrl.isEmpty || !context.mounted) return;
    final loc = AppLocale(ref.read(localeProvider));
    await showDialog<void>(
      context: context,
      barrierDismissible: !info.forceUpdate,
      builder: (_) => PopScope(canPop: !info.forceUpdate, child: _UpdateDialog(info: info, loc: loc)),
    );
  } catch (_) {
    // Offline or old server: never block the app on the update check.
  }
}

enum _Step { ask, downloading, installing, failed }

class _UpdateDialog extends StatefulWidget {
  final AppUpdateInfo info;
  final AppLocale loc;

  const _UpdateDialog({required this.info, required this.loc});

  @override
  State<_UpdateDialog> createState() => _UpdateDialogState();
}

class _UpdateDialogState extends State<_UpdateDialog> {
  _Step _step = _Step.ask;
  double _progress = 0;
  String _error = '';
  StreamSubscription<OtaEvent>? _sub;

  AppLocale get loc => widget.loc;

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  void _start() {
    setState(() {
      _step = _Step.downloading;
      _progress = 0;
      _error = '';
    });
    try {
      _sub = OtaUpdate()
          .execute(resolveServerUrl(widget.info.downloadUrl), destinationFilename: 'dramabiliki-update.apk')
          .listen(_onEvent, onError: (Object e) => _fail(e.toString()));
    } catch (e) {
      _fail(e.toString());
    }
  }

  void _onEvent(OtaEvent event) {
    if (!mounted) return;
    switch (event.status) {
      case OtaStatus.DOWNLOADING:
        setState(() => _progress = (double.tryParse(event.value ?? '') ?? 0) / 100);
      case OtaStatus.INSTALLING:
      case OtaStatus.INSTALLATION_DONE:
        setState(() => _step = _Step.installing);
      case OtaStatus.PERMISSION_NOT_GRANTED_ERROR:
        _fail(loc.t('update_permission'));
      case OtaStatus.ALREADY_RUNNING_ERROR:
        break;
      default:
        _fail(event.value ?? event.status.name);
    }
  }

  void _fail(String message) {
    if (!mounted) return;
    setState(() {
      _step = _Step.failed;
      _error = message;
    });
  }

  Future<void> _openInBrowser() async {
    await launchUrl(Uri.parse(resolveServerUrl(widget.info.downloadUrl)), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final info = widget.info;
    return AlertDialog(
      title: Row(
        children: [
          const Icon(Icons.system_update_rounded, color: AppTheme.primary),
          const SizedBox(width: 10),
          Expanded(child: Text(loc.t(info.forceUpdate ? 'update_required' : 'update_available'))),
        ],
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${loc.t('update_desc')} (${AppConstants.appVersion} → ${info.latestVersion})',
              style: const TextStyle(color: AppTheme.textSecondary)),
          if (_step == _Step.ask && info.releaseNotes.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(info.releaseNotes, style: const TextStyle(height: 1.4)),
          ],
          if (_step == _Step.downloading) ...[
            const SizedBox(height: 18),
            ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: _progress > 0 ? _progress : null,
                minHeight: 6,
                backgroundColor: AppTheme.surfaceLight,
                valueColor: const AlwaysStoppedAnimation(AppTheme.primary),
              ),
            ),
            const SizedBox(height: 8),
            Text('${loc.t('update_downloading')} ${(_progress * 100).round()} %',
                style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13)),
          ],
          if (_step == _Step.installing) ...[
            const SizedBox(height: 14),
            Text(loc.t('update_install_hint'), style: const TextStyle(height: 1.4)),
          ],
          if (_step == _Step.failed) ...[
            const SizedBox(height: 14),
            Text(loc.t('update_failed'), style: const TextStyle(color: Color(0xFFFF6B81))),
            if (_error.isNotEmpty)
              Text(_error, maxLines: 3, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: AppTheme.textMuted, fontSize: 12)),
          ],
        ],
      ),
      actions: [
        if (!info.forceUpdate && _step != _Step.downloading)
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(loc.t('later'), style: const TextStyle(color: AppTheme.textSecondary)),
          ),
        if (_step == _Step.failed)
          TextButton(onPressed: _openInBrowser, child: Text(loc.t('update_browser'))),
        if (_step == _Step.ask || _step == _Step.failed || _step == _Step.installing)
          ElevatedButton.icon(
            icon: Icon(_step == _Step.ask ? Icons.download_rounded : Icons.refresh_rounded),
            label: Text(loc.t(_step == _Step.ask ? 'update_now' : 'retry')),
            onPressed: _start,
          ),
      ],
    );
  }
}
