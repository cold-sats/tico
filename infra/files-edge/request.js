import cf from 'cloudfront';
import crypto from 'crypto';

const store = cf.kvs();
const domain = '__FILES_DOMAIN__';

function deny(status) {
    return {statusCode: status, headers: {
        'content-security-policy': {value: "default-src 'none'; sandbox"},
        'x-content-type-options': {value: 'nosniff'},
        'referrer-policy': {value: 'no-referrer'},
        'cache-control': {value: 'no-store'}
    }};
}

function one(query, name) {
    const item = query[name];
    return item && !item.multiValue && typeof item.value === 'string' ? item.value : '';
}

function equal(a, b) {
    if (a.length !== b.length) return false;
    let diff = 0;
    for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return diff === 0;
}

async function handler(event) {
    const request = event.request;
    const path = request.uri;
    if (!/^\/(blobs|visuals)\/([0-9a-f]{2})\/(\2[0-9a-f]{62})$/.test(path)) return deny(404);
    if (request.method !== 'GET' && request.method !== 'HEAD') return deny(403);
    const hostHeader = request.headers.host;
    const host = hostHeader && !hostHeader.multiValue ? hostHeader.value : '';
    const label = host.slice(0, -(domain.length + 1));
    if (!host.endsWith('.' + domain) || !/^[a-z0-9](?:[a-z0-9-]{0,55}[a-z0-9])?-files$/.test(label)) return deny(403);
    const query = request.querystring;
    const expiry = one(query, 'e');
    const key = one(query, 'k');
    const signature = one(query, 's');
    const now = Math.floor(Date.now() / 1000);
    if (!/^[0-9]{1,12}$/.test(expiry) || Number(expiry) <= now || Number(expiry) > now + 300 ||
        !/^[A-Za-z0-9_-]{1,64}$/.test(key) || !/^[A-Za-z0-9_-]{43}$/.test(signature)) return deny(403);
    try {
        // Only HQ writes this mapping; object writers never choose the tenant prefix or key.
        const company = JSON.parse(await store.get(host));
        if (!/^c\/[a-z0-9][a-z0-9-]{0,63}\/$/.test(company.prefix) ||
            company.signing.key_id !== key || typeof company.signing.secret !== 'string' ||
            company.signing.secret.length < 32 || company.signing.secret.length > 256) return deny(403);
        const expected = crypto.createHmac('sha256', company.signing.secret)
            .update(host + '\n' + path + '\n' + expiry).digest('base64url');
        if (!equal(expected, signature)) return deny(403);
        request.uri = '/' + company.prefix.slice(0, -1) + path;
        // Do not forward cookies, signatures or S3 response-header override parameters.
        request.querystring = {};
        request.cookies = {};
        return request;
    } catch (error) {
        return deny(403);
    }
}
