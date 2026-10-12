import 'constants.dart';

/// Paths served by our own bridge (as opposed to external CDNs), most specific first.
const _bridgePaths = ['/download/', '/stream/', '/subtitles/', '/media/covers/'];

/// Rebuilds links pointing to our bridge with the server address built into the app,
/// so a wrong host in the server configuration can never break downloads or images.
/// External URLs (e.g. CDN covers) are returned unchanged.
String resolveServerUrl(String url) {
  if (url.isEmpty) return url;
  final uri = Uri.tryParse(url);
  if (uri == null) return url;
  for (final marker in _bridgePaths) {
    final index = uri.path.indexOf(marker);
    if (index >= 0) {
      final base = Uri.parse(AppConstants.defaultBaseUrl);
      return base.replace(path: uri.path.substring(index), query: uri.hasQuery ? uri.query : null).toString();
    }
  }
  return url;
}
