// Cloudflare Pages Function - proxies /api/* requests through the tunnel
// This bypasses Cloudflare Pages' GET-only limitation for POST requests
// and allows the tunnel to properly route API traffic.

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  
  // Rewrite path: remove /api prefix and forward to the tunnel
  const apiPath = url.pathname; // e.g., /api/credits, /api/wake
  
  // The tunnel's internal .cfargotunnel.com address
  // Uses the tunnel ID to route through the tunnel directly
  const tunnelHost = '2f485c4b-446b-4401-9289-b6db8d4a837e.cfargotunnel.com';
  const targetUrl = `https://${tunnelHost}${apiPath}${url.search}`;
  
  // Forward the request method, headers, and body
  const init = {
    method: request.method,
    headers: {
      // Only pass through essential headers
      'Content-Type': request.headers.get('Content-Type') || '',
      'Accept': request.headers.get('Accept') || 'application/json',
    },
  };
  
  // Forward body for POST/PUT/PATCH requests
  if (['POST', 'PUT', 'PATCH'].includes(request.method)) {
    try {
      init.body = await request.clone().text();
    } catch (e) {
      // No body or error reading
    }
  }
  
  try {
    const response = await fetch(targetUrl, init);
    
    // Return the response with CORS headers for browser access
    const responseHeaders = new Headers(response.headers);
    responseHeaders.set('Access-Control-Allow-Origin', '*');
    responseHeaders.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    responseHeaders.set('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
