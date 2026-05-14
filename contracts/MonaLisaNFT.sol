// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title MonaLisaNFT
 * @notice ERC-721 NFT collection: Mona Lisa × Pokemon / Hunter×Hunter crossover
 *
 * Self-contained ERC-721 implementation (no external deps).
 * SVG art stored on-chain, tokenURI returns base64-encoded data URI.
 */
contract MonaLisaNFT {
    // ── ERC-721 events ────────────────────────────
    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event Approval(address indexed owner, address indexed approved, uint256 indexed tokenId);
    event ApprovalForAll(address indexed owner, address indexed operator, bool approved);

    // ── ERC-721 state ─────────────────────────────
    string private _name;
    string private _symbol;
    mapping(uint256 => address) private _owners;
    mapping(address => uint256) private _balances;
    mapping(uint256 => address) private _tokenApprovals;
    mapping(address => mapping(address => bool)) private _operatorApprovals;

    // ── NFT data ──────────────────────────────────
    struct TokenMeta {
        string name;       // e.g. "Mona Lisa Illustrator"
        string character;  // e.g. "Pikachu", "Gon Freecss"
        string charType;   // e.g. "Electric", "強化系"
        string rarity;     // "Legendary", "Mythic", "Epic", "Rare"
        uint256 price;     // mint price in wei
    }

    TokenMeta[] private _meta;
    mapping(uint256 => string) private _svgs;  // full SVG per token
    uint256 private _totalMinted;
    address public owner;

    uint256 public constant MAX_SUPPLY = 22;

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor(
        string memory name_,
        string memory symbol_,
        TokenMeta[] memory meta_
    ) {
        _name = name_;
        _symbol = symbol_;
        owner = msg.sender;

        uint256 len = meta_.length;
        require(len <= MAX_SUPPLY, "Exceeds max supply");

        for (uint256 i = 0; i < len; i++) {
            _meta.push(meta_[i]);
        }
    }

    /// @notice Set SVG data for a batch of tokens (reduces tx count)
    /// @param tokenIds Array of token IDs (must match svgs length)
    /// @param svgs_ Array of SVG strings
    function batchSetSVGs(uint256[] calldata tokenIds, string[] calldata svgs_) external onlyOwner {
        require(tokenIds.length == svgs_.length, "Length mismatch");
        require(tokenIds.length > 0, "Empty batch");
        require(svgs_.length > 0, "Empty batch");
        for (uint256 i = 0; i < tokenIds.length; i++) {
            require(tokenIds[i] < _meta.length, "Invalid token");
            _svgs[tokenIds[i]] = svgs_[i];
        }
    }

    /// @notice Set SVG for a single token
    function setSVG(uint256 tokenId, string calldata svg_) external onlyOwner {
        require(tokenId < _meta.length, "Invalid token");
        _svgs[tokenId] = svg_;
    }

    // ── ERC-721 public functions ──────────────────

    function name() external view returns (string memory) { return _name; }
    function symbol() external view returns (string memory) { return _symbol; }

    function balanceOf(address account) external view returns (uint256) {
        require(account != address(0), "Zero address");
        return _balances[account];
    }

    function ownerOf(uint256 tokenId) public view returns (address) {
        address addr = _owners[tokenId];
        require(addr != address(0), "Nonexistent token");
        return addr;
    }

    function approve(address to, uint256 tokenId) external {
        address tokenOwner = _owners[tokenId];
        require(tokenOwner == msg.sender || _operatorApprovals[tokenOwner][msg.sender], "Not authorized");
        _tokenApprovals[tokenId] = to;
        emit Approval(tokenOwner, to, tokenId);
    }

    function getApproved(uint256 tokenId) external view returns (address) {
        require(_owners[tokenId] != address(0), "Nonexistent token");
        return _tokenApprovals[tokenId];
    }

    function setApprovalForAll(address operator, bool approved) external {
        _operatorApprovals[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }

    function isApprovedForAll(address account, address operator) external view returns (bool) {
        return _operatorApprovals[account][operator];
    }

    function transferFrom(address from, address to, uint256 tokenId) public {
        require(_isApprovedOrOwner(msg.sender, tokenId), "Not approved");
        _transfer(from, to, tokenId);
    }

    function safeTransferFrom(address from, address to, uint256 tokenId) external {
        safeTransferFrom(from, to, tokenId, "");
    }

    function safeTransferFrom(address from, address to, uint256 tokenId, bytes memory data) public {
        require(_isApprovedOrOwner(msg.sender, tokenId), "Not approved");
        _transfer(from, to, tokenId);
        require(_checkOnERC721Received(from, to, tokenId, data), "ERC721: transfer to non-ERC721Receiver");
    }

    function supportsInterface(bytes4 interfaceId) external pure returns (bool) {
        return interfaceId == 0x80ac58cd  // ERC-721
            || interfaceId == 0x5b5e139f  // ERC-721 Metadata
            || interfaceId == 0x01ffc9a7; // ERC-165
    }

    // ── Minting ───────────────────────────────────

    function mint(uint256 tokenId) external payable {
        require(tokenId < _meta.length, "Invalid token");
        require(_owners[tokenId] == address(0), "Already minted");
        require(msg.value >= _meta[tokenId].price, "Insufficient payment");
        require(_totalMinted < MAX_SUPPLY, "Max supply reached");

        _totalMinted++;
        _safeMint(msg.sender, tokenId);

        // Refund excess payment
        if (msg.value > _meta[tokenId].price) {
            payable(msg.sender).transfer(msg.value - _meta[tokenId].price);
        }
    }

    function mintTo(address to, uint256 tokenId) external onlyOwner {
        require(tokenId < _meta.length, "Invalid token");
        require(_owners[tokenId] == address(0), "Already minted");
        require(_totalMinted < MAX_SUPPLY, "Max supply reached");
        _totalMinted++;
        _safeMint(to, tokenId);
    }

    function totalSupply() external view returns (uint256) { return _totalMinted; }
    function totalTokens() external view returns (uint256) { return _meta.length; }

    function getTokenMeta(uint256 tokenId) external view returns (TokenMeta memory) {
        require(tokenId < _meta.length, "Invalid token");
        return _meta[tokenId];
    }

    // ── Withdraw ──────────────────────────────────

    function withdraw() external onlyOwner {
        uint256 bal = address(this).balance;
        require(bal > 0, "No balance");
        payable(owner).transfer(bal);
    }

    // ── tokenURI (ERC-721 Metadata) ──────────────

    function tokenURI(uint256 tokenId) public view returns (string memory) {
        require(tokenId < _meta.length, "Invalid token");
        require(bytes(_svgs[tokenId]).length > 0, "SVG not set");

        string memory svg = _svgs[tokenId];
        string memory imgEncoded = Base64.encode(bytes(svg));

        string memory json = string(abi.encodePacked(
            '{"name":"', _meta[tokenId].name, '",',
            '"description":"Mona Lisa x ', _meta[tokenId].character, ' crossover NFT from the Legendary Encounters / Nen Encounters collection.",',
            '"image":"data:image/svg+xml;base64,', imgEncoded, '",',
            '"attributes":[',
            '{"trait_type":"Character","value":"', _meta[tokenId].character, '"},',
            '{"trait_type":"', (_isPokemon(tokenId) ? "Type" : "Nen"), '","value":"', _meta[tokenId].charType, '"},',
            '{"trait_type":"Rarity","value":"', _meta[tokenId].rarity, '"},',
            '{"trait_type":"Series","value":"', (_isPokemon(tokenId) ? "Legendary Encounters" : "Nen Encounters"), '"}',
            ']}'
        ));

        return string(abi.encodePacked("data:application/json;base64,", Base64.encode(bytes(json))));
    }

    // ── Internal ──────────────────────────────────

    function _isPokemon(uint256 tokenId) private view returns (bool) {
        return tokenId < 10; // IDs 0-9 = Pokemon, 10-21 = HxH
    }

    function _isApprovedOrOwner(address spender, uint256 tokenId) private view returns (bool) {
        address tokenOwner = _owners[tokenId];
        return (spender == tokenOwner
            || _tokenApprovals[tokenId] == spender
            || _operatorApprovals[tokenOwner][spender]);
    }

    function _transfer(address from, address to, uint256 tokenId) private {
        require(_owners[tokenId] == from, "Incorrect owner");
        require(to != address(0), "Zero address");

        // Clear approvals
        delete _tokenApprovals[tokenId];

        _balances[from]--;
        _balances[to]++;
        _owners[tokenId] = to;

        emit Transfer(from, to, tokenId);
    }

    function _safeMint(address to, uint256 tokenId) private {
        _owners[tokenId] = to;
        _balances[to]++;
        emit Transfer(address(0), to, tokenId);
    }

    function _checkOnERC721Received(address from, address to, uint256 tokenId, bytes memory data) private returns (bool) {
        if (!isContract(to)) return true;

        (bool success, bytes memory ret) = to.call(
            abi.encodeWithSelector(0x150b7a02, msg.sender, from, tokenId, data)
        );
        if (success && ret.length == 32) {
            bytes4 retVal = abi.decode(ret, (bytes4));
            return retVal == 0x150b7a02;
        }
        return false;
    }

    function isContract(address addr) private view returns (bool) {
        uint256 size;
        assembly { size := extcodesize(addr) }
        return size > 0;
    }
}

// ── Minimal base64 encoder ─────────────────────

library Base64 {
    string constant TABLE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    function encode(bytes memory data) internal pure returns (string memory) {
        if (data.length == 0) return "";

        uint256 encodedLen = 4 * ((data.length + 2) / 3);
        bytes memory result = new bytes(encodedLen);

        uint256 i;
        uint256 j;

        while (i + 3 <= data.length) {
            uint256 b0 = uint8(data[i++]);
            uint256 b1 = uint8(data[i++]);
            uint256 b2 = uint8(data[i++]);

            uint256 triple = (b0 << 16) | (b1 << 8) | b2;

            result[j++] = bytes(TABLE)[(triple >> 18) & 0x3F];
            result[j++] = bytes(TABLE)[(triple >> 12) & 0x3F];
            result[j++] = bytes(TABLE)[(triple >> 6) & 0x3F];
            result[j++] = bytes(TABLE)[triple & 0x3F];
        }

        uint256 remaining = data.length - i;
        if (remaining == 1) {
            uint256 b0 = uint8(data[i++]);
            uint256 triple = b0 << 16;
            result[j++] = bytes(TABLE)[(triple >> 18) & 0x3F];
            result[j++] = bytes(TABLE)[(triple >> 12) & 0x3F];
            result[j++] = bytes("=")[0];
            result[j++] = bytes("=")[0];
        } else if (remaining == 2) {
            uint256 b0 = uint8(data[i++]);
            uint256 b1 = uint8(data[i++]);
            uint256 triple = (b0 << 16) | (b1 << 8);
            result[j++] = bytes(TABLE)[(triple >> 18) & 0x3F];
            result[j++] = bytes(TABLE)[(triple >> 12) & 0x3F];
            result[j++] = bytes(TABLE)[(triple >> 6) & 0x3F];
            result[j++] = bytes("=")[0];
        }

        return string(result);
    }
}
