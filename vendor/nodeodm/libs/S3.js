/*
NodeODM App and REST API to access ODM.
Copyright (C) 2016 NodeODM Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/
"use strict";

const config = require('../config');

// Local Aerial Mapper intentionally has no cloud-export dependency or egress
// path. Keep NodeODM's S3 interface in place so the upstream task lifecycle
// stays unchanged, but fail startup if someone accidentally configures S3.
module.exports = {
    enabled: function(){
        return false;
    },

    initialize: function(cb){
        if (config.s3Endpoint || config.s3Bucket){
            cb(new Error("S3 export is disabled in Local Aerial Mapper"));
        }else{
            cb();
        }
    },

    uploadPaths: function(srcFolder, bucket, dstFolder, paths, cb){
        cb(new Error("S3 export is disabled in Local Aerial Mapper"));
    }
};
