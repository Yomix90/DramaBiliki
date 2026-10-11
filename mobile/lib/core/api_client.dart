import 'package:dio/dio.dart';
import 'preferences.dart';

class ApiClient {
  late final Dio dio;
  final PreferencesService preferences;

  // Shared in-flight device auth, so parallel 401s trigger a single re-auth.
  Future<String?>? _authInFlight;

  ApiClient(this.preferences) {
    dio = Dio(
      BaseOptions(
        baseUrl: preferences.getBaseUrl(),
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 20),
        headers: {
          'Accept': 'application/json',
        },
      ),
    );

    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          // Attach Base URL dynamically in case changed in settings
          options.baseUrl = preferences.getBaseUrl();

          final token = preferences.getAuthToken();
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }

          if (!options.queryParameters.containsKey('lang')) {
            options.queryParameters['lang'] = preferences.getLanguage();
          }

          return handler.next(options);
        },
        onError: (DioException error, handler) async {
          // Expired or unknown token: re-register the device once and replay the request.
          final req = error.requestOptions;
          final isAuthCall = req.path.endsWith('/auth/device');
          if (error.response?.statusCode == 401 && !isAuthCall && req.extra['retried'] != true) {
            await preferences.clearAuthToken();
            final token = await authenticateDevice();
            if (token != null) {
              req.extra['retried'] = true;
              req.headers['Authorization'] = 'Bearer $token';
              try {
                final response = await dio.fetch(req);
                return handler.resolve(response);
              } on DioException catch (e) {
                return handler.next(e);
              }
            }
          }
          return handler.next(error);
        },
      ),
    );
  }

  /// Registers this device with the bridge and stores the returned JWT.
  /// Returns the token, or null when the server is unreachable.
  Future<String?> authenticateDevice() {
    return _authInFlight ??= _doAuthenticate().whenComplete(() => _authInFlight = null);
  }

  Future<String?> _doAuthenticate() async {
    try {
      final response = await dio.post('/api/v1/auth/device', data: {
        'device_id': preferences.getDeviceId(),
        'platform_os': 'android',
        'preferred_language': preferences.getLanguage(),
      });
      final token = (response.data as Map<String, dynamic>?)?['access_token'] as String?;
      if (token != null && token.isNotEmpty) {
        await preferences.setAuthToken(token);
        return token;
      }
    } catch (_) {
      // Offline: the app keeps working in anonymous mode.
    }
    return null;
  }

  void updateBaseUrl(String newUrl) {
    dio.options.baseUrl = newUrl;
  }
}
